"""Module service layer.

Thin facade over :class:`ModuleRegistry` + the ``core_module`` tables.
For Etapa 1 this service is read-mostly: it discovers modules, reconciles
the DB, and answers ``list``/``info``/``status``/``doctor`` queries.

Install, uninstall and upgrade flows arrive in Etapa 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .alembic_paths import resolve_module_branch_head
from .apps import modules_disabled_by_app
from .base import BaseModule
from .db_models import ModuleOperationLog, ModuleRecord
from .gate import module_gate
from .loader import discover_modules
from .manifest import Manifest, ManifestError
from .operation_log import LogEntry, log_entry_from_row
from .registry import module_registry
from .state import ModuleCategory, ModuleState
from .topology import MissingDependencyError, topological_sort

logger = logging.getLogger(__name__)


async def applied_revisions(db: AsyncSession) -> set[str] | None:
    """Every revision ``alembic_version`` says this database has run.

    The only honest answer to "is this module's branch applied?".
    ``core_module.applied_revision`` is bookkeeping that can be wrong;
    this table is what Alembic itself reads.

    **``None`` when there is no ``alembic_version`` table at all**, which
    is a different question from an empty one and needs the opposite
    answer. No table means the schema did not come from Alembic — it came
    from ``metadata.create_all``, as the test suite's does — so every
    table is already at the shape its models describe and there is
    nothing for the catch-up to apply. Told "nothing is applied" instead,
    the catch-up replays each branch from its base onto tables that
    already exist, every ``CREATE TABLE`` raises, and the boot leaves
    those modules unmounted: the suite's whole app comes up with no
    agenda in it.

    A table that exists and simply does not list a branch is the real
    case this function was written for: that branch has not run, and the
    catch-up is what must run it.

    ``to_regclass`` answers ``NULL`` for a missing table instead of
    raising: selecting from one directly would abort the caller's
    transaction, and this runs inside reconcile's.
    """
    try:
        async with db.begin_nested():
            if await db.scalar(text("SELECT to_regclass('alembic_version')")) is None:
                return None
            rows = await db.execute(text("SELECT version_num FROM alembic_version"))
            return {row[0] for row in rows}
    except Exception:
        # The table is there and could not be read. Assuming nothing is
        # applied is the safe direction here: the upgrade it provokes is
        # a no-op when the branch had in fact run.
        logger.exception("Could not read alembic_version; assuming no branch is applied")
        return set()


def _ran(branch_head: str | None, applied: set[str] | None) -> bool:
    """Whether ``branch_head`` may be recorded as already applied.

    ``applied is None`` — no ``alembic_version`` at all — means the
    schema was built from the models, so every branch counts as run.
    """
    if branch_head is None:
        return False
    return applied is None or branch_head in applied


async def installed_module_names(db: AsyncSession) -> set[str]:
    """Names of the modules ``core_module`` says are live.

    The single question the boot sequence asks the database before it
    mounts anything (audit S1). Only ``installed`` qualifies: a record
    still in a transient state (``to_install`` / ``to_remove``) either
    has not been processed yet or failed half-way, and a module with
    partially created or partially dropped tables must not serve
    traffic.

    ``apps.json`` then holds back the modules of any App the deployment
    has disabled (ADR 0038). Their records stay ``installed`` — nothing
    about them changed — they are just not part of what runs.
    """
    result = await db.execute(
        select(ModuleRecord.name).where(ModuleRecord.state == ModuleState.INSTALLED.value)
    )
    return set(result.scalars()) - modules_disabled_by_app()


# States in which a module does not serve. One that is still mounted
# under any of them was turned off after this process started.
_OFF_STATES = (
    ModuleState.DISABLED.value,
    ModuleState.TO_REMOVE.value,
    ModuleState.UNINSTALLED.value,
)


async def sync_module_gate(session_factory: async_sessionmaker[AsyncSession], ticket: int) -> None:
    """Close the gate for what the database says is off and is mounted here.

    The other half of :mod:`~app.core.plugins.gate`: the state changed in
    another process — the CLI, or another backend — and this one finds
    out by asking. Only mounted modules are named: an unmounted one has
    no routes to refuse, and its path should go on answering 404.

    A failed read keeps the gate as it was. Refusing a module because
    the database blinked would take a working screen away for nothing.
    """
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(ModuleRecord.name).where(ModuleRecord.state.in_(_OFF_STATES))
            )
            off = set(result.scalars())
    except Exception:
        logger.warning("Could not read module states for the gate; keeping it as it was")
        return

    mounted = {module.name for module in module_registry.list_modules()}
    module_gate.apply_sync(mounted & off, ticket)


class ModuleOperationError(RuntimeError):
    """Raised by :class:`ModuleService` install/uninstall/upgrade when a
    transition is not allowed (blocked dep, legacy module, etc.)."""


@dataclass
class ModuleInfo:
    """Projection of a module + its DB row for CLI/API output."""

    name: str
    version: str
    state: ModuleState
    category: ModuleCategory
    removable: bool
    auto_install: bool
    installed_at: datetime | None
    last_state_change: datetime
    base_revision: str | None
    applied_revision: str | None
    error_message: str | None
    error_at: datetime | None
    summary: str
    depends: list[str]
    in_disk: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "state": self.state.value,
            "category": self.category.value,
            "removable": self.removable,
            "auto_install": self.auto_install,
            "installed_at": self.installed_at.isoformat() if self.installed_at else None,
            "last_state_change": self.last_state_change.isoformat(),
            "base_revision": self.base_revision,
            "applied_revision": self.applied_revision,
            "error_message": self.error_message,
            "error_at": self.error_at.isoformat() if self.error_at else None,
            "summary": self.summary,
            "depends": self.depends,
            "in_disk": self.in_disk,
        }


@dataclass
class DoctorReport:
    """Diagnostic output from :meth:`ModuleService.doctor`."""

    orphans: list[str]
    missing_dependencies: list[tuple[str, str]]
    manifest_errors: list[tuple[str, str]]
    errored_modules: list[tuple[str, str]]

    @property
    def ok(self) -> bool:
        return not (
            self.orphans
            or self.missing_dependencies
            or self.manifest_errors
            or self.errored_modules
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "orphans": self.orphans,
            "missing_dependencies": [
                {"module": m, "missing": dep} for m, dep in self.missing_dependencies
            ],
            "manifest_errors": [{"module": m, "error": err} for m, err in self.manifest_errors],
            "errored_modules": [{"module": m, "error": err} for m, err in self.errored_modules],
        }


class ModuleService:
    """Service-layer operations on modules.

    Usage: instantiate per request/CLI invocation with a live session.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- Discovery + reconciliation -------------------------------------

    def discovered(self) -> list[BaseModule]:
        """Every module found on disk, whatever its install state.

        The service operates on the full inventory: it has to be able to
        install a module that is not running yet, and to uninstall one
        that is. ``list_modules()`` (installed only) is for consumers
        that must behave as if uninstalled modules do not exist.
        """
        return module_registry.list_discovered()

    async def reconcile_with_db(self) -> None:
        """Ensure ``core_module`` contains one row per discovered module.

        For v1 (Etapa 1): discovered modules that are new in the DB are
        inserted as ``installed`` (their routers/handlers are already
        mounted by :func:`load_modules`, so they are effectively live).
        Discovered modules already in the DB have their ``version`` +
        ``manifest_snapshot`` refreshed if the version changed.

        Modules present in DB but missing from disk are left alone here
        — :meth:`doctor` surfaces them as orphans.
        """
        discovered = self.discovered()
        existing = await self._load_existing_records()
        now = datetime.now(UTC)
        # What Alembic actually ran, so a branch is never recorded as
        # applied on the strength of being on disk.
        on_disk_applied = await applied_revisions(self.db)

        for module in discovered:
            try:
                manifest = module.get_manifest()
            except ManifestError as exc:
                logger.error(
                    "Skipping reconcile for %s (manifest invalid): %s",
                    module.name,
                    exc,
                )
                continue

            # Resolve the Alembic branch head for modules that ship their
            # own migrations — without this, uninstall cannot safely
            # downgrade because the processor only populates
            # ``base_revision`` during the install flow, which auto-
            # installed modules never go through.
            branch_head = resolve_module_branch_head(module)

            # The branch-isolation invariant for ``removable=True`` is
            # enforced at manifest-validation time (see
            # :mod:`manifest_validator`) — reconcile trusts it.
            record = existing.get(module.name)
            if record is None:
                # Modules with ``auto_install=False`` start ``disabled``:
                # their tables exist (ADR 0035 — every database carries
                # the whole schema) but nothing is mounted, their
                # lifecycle install() hook is NOT called and their event
                # handlers do not fire until somebody enables them.
                #
                # Either way the branch is recorded at head *if the
                # database has really run it* — a new database
                # bootstrapped with ``alembic upgrade heads`` has, and
                # the processor keeps both states migrated from here on.
                # A module arriving in an existing deployment has not,
                # and recording head would tell the processor's catch-up
                # there is nothing to apply.
                if manifest.auto_install:
                    initial_state = ModuleState.INSTALLED.value
                    initial_installed_at = now
                else:
                    initial_state = ModuleState.DISABLED.value
                    initial_installed_at = None

                self.db.add(
                    ModuleRecord(
                        name=manifest.name,
                        version=manifest.version,
                        state=initial_state,
                        category=manifest.category.value,
                        removable=manifest.removable,
                        auto_install=manifest.auto_install,
                        installed_at=initial_installed_at,
                        last_state_change=now,
                        manifest_snapshot=manifest.to_snapshot(),
                        base_revision=branch_head,
                        applied_revision=(
                            branch_head if _ran(branch_head, on_disk_applied) else None
                        ),
                    )
                )
                logger.info(
                    "Reconciled: inserted new module %s (state=%s)",
                    manifest.name,
                    initial_state,
                )
                continue

            if record.version != manifest.version:
                logger.info(
                    "Reconciled: %s version %s -> %s",
                    manifest.name,
                    record.version,
                    manifest.version,
                )
                record.version = manifest.version

            # A module that was never installed used to rest in
            # ``uninstalled`` with its tables in place. That is what
            # ``disabled`` means now (ADR 0035). A real uninstall leaves
            # ``base_revision`` set and clears ``applied_revision`` — the
            # tables were dropped on purpose — and is left alone.
            really_uninstalled = (
                record.base_revision is not None and record.applied_revision is None
            )
            if record.state == ModuleState.UNINSTALLED.value and not really_uninstalled:
                record.state = ModuleState.DISABLED.value
                record.last_state_change = now

            # Always refresh the snapshot so DB stays in sync with disk.
            record.manifest_snapshot = manifest.to_snapshot()
            record.category = manifest.category.value
            record.removable = manifest.removable
            record.auto_install = manifest.auto_install

            # Backfill base_revision for modules reconciled before this
            # logic existed — enables uninstall of already-installed
            # removable modules.
            #
            # ``applied_revision`` is only filled when ``alembic_version``
            # confirms the branch ran. Both a database predating
            # ``base_revision`` and a module that shipped its first
            # migration *after* it was installed arrive here with
            # ``base_revision is None``, and the two need opposite
            # answers: the first really is migrated, the second has no
            # tables at all. Assuming the first is how
            # ``reports_summary_schedule`` ended up missing in production
            # while the record claimed head — the catch-up in
            # ``PendingProcessor._migrate_installed`` skips any branch
            # whose recorded revision already equals the head, so the
            # claim stopped the one step that would have created it.
            if record.base_revision is None and branch_head is not None:
                record.base_revision = branch_head
                if record.applied_revision is None and _ran(branch_head, on_disk_applied):
                    record.applied_revision = branch_head

        await self.db.commit()

    async def _load_existing_records(self) -> dict[str, ModuleRecord]:
        result = await self.db.execute(select(ModuleRecord))
        return {r.name: r for r in result.scalars()}

    # --- Query ----------------------------------------------------------

    async def list_modules(self) -> list[ModuleInfo]:
        """Return combined in-memory + DB view of all known modules."""
        records = await self._load_existing_records()
        discovered = {m.name: m for m in self.discovered()}

        names = sorted(set(records) | set(discovered))
        infos: list[ModuleInfo] = []

        for name in names:
            record = records.get(name)
            module = discovered.get(name)

            manifest = self._safe_manifest(module) if module else None
            summary = manifest.summary if manifest else ""
            depends = (
                list(manifest.depends)
                if manifest
                else list((record.manifest_snapshot or {}).get("depends", []))
            )
            version = manifest.version if manifest else (record.version if record else "")
            category = (
                manifest.category
                if manifest
                else ModuleCategory(record.category)
                if record
                else ModuleCategory.OFFICIAL
            )
            state = ModuleState(record.state) if record else ModuleState.UNINSTALLED

            # `_mark_error` only fires while a pending op is in-flight, so
            # an INSTALLED record carrying `error_message` is stale by
            # construction — hide it from the card.
            stale_error = record is not None and state == ModuleState.INSTALLED
            err_msg = None if stale_error else (record.error_message if record else None)
            err_at = None if stale_error else (record.error_at if record else None)

            infos.append(
                ModuleInfo(
                    name=name,
                    version=version,
                    state=state,
                    category=category,
                    removable=record.removable if record else True,
                    auto_install=record.auto_install if record else False,
                    installed_at=record.installed_at if record else None,
                    last_state_change=(record.last_state_change if record else datetime.now(UTC)),
                    base_revision=record.base_revision if record else None,
                    applied_revision=record.applied_revision if record else None,
                    error_message=err_msg,
                    error_at=err_at,
                    summary=summary,
                    depends=depends,
                    in_disk=module is not None,
                )
            )

        return infos

    async def get_info(self, name: str) -> ModuleInfo | None:
        for info in await self.list_modules():
            if info.name == name:
                return info
        return None

    async def status(self) -> dict[str, Any]:
        """Summary: counts by state + list of pending + errored modules."""
        infos = await self.list_modules()
        by_state: dict[str, int] = {}
        pending: list[str] = []
        errored: list[str] = []

        for info in infos:
            by_state[info.state.value] = by_state.get(info.state.value, 0) + 1
            if info.state in {
                ModuleState.TO_INSTALL,
                ModuleState.TO_UPGRADE,
                ModuleState.TO_REMOVE,
            }:
                pending.append(info.name)
            if info.error_message and info.state != ModuleState.INSTALLED:
                errored.append(info.name)

        return {
            "by_state": by_state,
            "pending": pending,
            "errored": errored,
            "total": len(infos),
        }

    async def doctor(self) -> DoctorReport:
        """Run diagnostic checks across discovered + persisted modules."""
        records = await self._load_existing_records()
        discovered = {m.name: m for m in self.discovered()}

        orphans: list[str] = [
            name
            for name, record in records.items()
            if name not in discovered
            and record.state not in (ModuleState.UNINSTALLED.value, ModuleState.DISABLED.value)
        ]

        manifest_errors: list[tuple[str, str]] = []
        for name, module in discovered.items():
            try:
                module.get_manifest()
            except ManifestError as exc:
                manifest_errors.append((name, str(exc)))

        known_names = set(discovered) | set(records)
        missing_deps: list[tuple[str, str]] = []
        for name, module in discovered.items():
            for dep in module.dependencies:
                if dep not in known_names:
                    missing_deps.append((name, dep))

        errored = [
            (name, record.error_message or "")
            for name, record in records.items()
            if record.error_message and record.state != ModuleState.INSTALLED.value
        ]

        return DoctorReport(
            orphans=orphans,
            missing_dependencies=missing_deps,
            manifest_errors=manifest_errors,
            errored_modules=errored,
        )

    async def operation_log(self, name: str, *, limit: int = 20) -> list[LogEntry]:
        """Return the most recent log entries for ``name`` (desc by id).

        Raises :class:`ModuleOperationError` if the module is unknown to
        the DB. ``limit`` is clamped by the caller.
        """
        records = await self._load_existing_records()
        if name not in records:
            raise ModuleOperationError(f"Unknown module: '{name}'")

        result = await self.db.execute(
            select(ModuleOperationLog)
            .where(ModuleOperationLog.module_name == name)
            .order_by(ModuleOperationLog.id.desc())
            .limit(limit)
        )
        return [log_entry_from_row(row) for row in result.scalars()]

    async def orphan(self, name: str) -> bool:
        """Mark a missing-from-disk module as ``uninstalled`` for recovery."""
        record = (
            await self.db.execute(select(ModuleRecord).where(ModuleRecord.name == name))
        ).scalar_one_or_none()
        if record is None:
            return False

        record.state = ModuleState.UNINSTALLED.value
        record.last_state_change = datetime.now(UTC)
        record.error_message = None
        record.error_at = None
        await self.db.commit()
        module_gate.unblock(name)
        return True

    # --- State transitions (no execution; processor handles that) -------

    async def install(self, name: str, *, force: bool = False) -> list[str]:
        """Mark ``name`` and every uninstalled dep as ``to_install``.

        Returns the ordered list of module names scheduled (topo order),
        including transitive dependencies. Caller is expected to trigger
        a restart — the lifespan processor executes pending operations.
        """
        module = self._require_discovered(name)
        manifest = module.get_manifest()
        if not manifest.installable and not force:
            raise ModuleOperationError(f"Module '{name}' is marked installable=False")

        records = await self._load_existing_records()
        chain = self._dependency_chain(name)
        scheduled: list[str] = []
        now = datetime.now(UTC)

        for dep_name in chain:
            dep_module = self._require_discovered(dep_name)
            dep_manifest = dep_module.get_manifest()
            record = records.get(dep_name)

            if record is None:
                self.db.add(
                    ModuleRecord(
                        name=dep_manifest.name,
                        version=dep_manifest.version,
                        state=ModuleState.TO_INSTALL.value,
                        category=dep_manifest.category.value,
                        removable=dep_manifest.removable,
                        auto_install=dep_manifest.auto_install,
                        last_state_change=now,
                        manifest_snapshot=dep_manifest.to_snapshot(),
                    )
                )
                scheduled.append(dep_name)
                continue

            if record.state == ModuleState.INSTALLED.value:
                continue
            if record.state in {
                ModuleState.TO_INSTALL.value,
                ModuleState.TO_UPGRADE.value,
            }:
                continue

            # Installing a module that was scheduled for removal cancels
            # the removal, so it must serve again.
            module_gate.unblock(dep_name)
            record.state = ModuleState.TO_INSTALL.value
            record.version = dep_manifest.version
            record.manifest_snapshot = dep_manifest.to_snapshot()
            record.category = dep_manifest.category.value
            record.removable = dep_manifest.removable
            record.auto_install = dep_manifest.auto_install
            record.last_state_change = now
            record.error_message = None
            record.error_at = None
            scheduled.append(dep_name)

        await self.db.commit()
        return scheduled

    async def enable(self, name: str) -> list[str]:
        """Enable ``name`` and every dependency that is not enabled yet.

        Enabling is the install flow: the processor finds the tables
        already there, so its migrate step is a no-op and the seed and
        lifecycle hook run as they would on a first install.
        """
        return await self.install(name)

    async def disable(self, name: str) -> None:
        """Stop ``name`` from running without touching its data.

        The record goes straight to ``disabled``: the next boot does not
        mount it, and its branch keeps being migrated so the schema never
        falls behind the modules that reference it (ADR 0035).

        Blocked while another enabled module declares ``name`` in its
        ``depends`` — that module's code imports this one's. There is no
        ``force``: the block is what keeps the running set coherent.
        """
        records = await self._load_existing_records()
        record = records.get(name)
        if record is None:
            raise ModuleOperationError(f"Unknown module: '{name}'")

        if record.state == ModuleState.DISABLED.value:
            return  # no-op

        if record.state != ModuleState.INSTALLED.value:
            raise ModuleOperationError(
                f"Module '{name}' is '{record.state}', only an enabled module can be disabled."
            )

        dependents = self._active_dependents(name, records)
        if dependents:
            raise ModuleOperationError(
                f"Cannot disable '{name}' — required by: {dependents}. Disable them first."
            )

        record.state = ModuleState.DISABLED.value
        record.last_state_change = datetime.now(UTC)
        record.error_message = None
        record.error_at = None
        await self.db.commit()

        # Still mounted until the restart; stop it answering meanwhile.
        module_gate.block(name)

    @staticmethod
    def _active_dependents(name: str, records: dict[str, ModuleRecord]) -> list[str]:
        """Modules that are live (or about to be) and depend on ``name``.

        ``integrates`` does not count: a module carries on without the
        ones it merely integrates with (ADR 0037).
        """
        return [
            other.name
            for other in records.values()
            if other.state
            in {
                ModuleState.INSTALLED.value,
                ModuleState.TO_INSTALL.value,
                ModuleState.TO_UPGRADE.value,
            }
            and name in (other.manifest_snapshot or {}).get("depends", [])
        ]

    @staticmethod
    def _schema_dependents(name: str, records: dict[str, ModuleRecord]) -> list[str]:
        """Modules that stand in the way of dropping ``name``'s tables.

        Two kinds. A module that is running and declares ``name`` in
        ``depends`` or ``integrates`` — it expects to find it. And any
        module whose own tables hold a foreign key into ``name``'s,
        running or not: a disabled module still has its tables (ADR
        0035), and the drop would fail against them or cascade.

        The second is read off the models rather than the manifests so a
        disabled module that merely *declares* a dependency, with no
        foreign key behind it, does not block a removal it would never
        notice.
        """
        target = module_registry.get(name)
        target_tables = {
            str(model.__tablename__)
            for model in (target.get_models() if target else [])
            if getattr(model, "__tablename__", None)
        }
        running = {
            ModuleState.INSTALLED.value,
            ModuleState.TO_INSTALL.value,
            ModuleState.TO_UPGRADE.value,
        }

        blockers: list[str] = []
        for other in records.values():
            if other.name == name or other.state == ModuleState.UNINSTALLED.value:
                continue
            snapshot = other.manifest_snapshot or {}
            declared = [*snapshot.get("depends", []), *snapshot.get("integrates", [])]
            if other.state in running and name in declared:
                blockers.append(other.name)
                continue
            module = module_registry.get(other.name)
            if module is not None and any(
                fk.column.table.name in target_tables
                for model in module.get_models()
                for fk in model.__table__.foreign_keys
            ):
                blockers.append(other.name)
        return blockers

    async def uninstall(self, name: str, *, force: bool = False) -> None:
        """Mark ``name`` as ``to_remove`` unless blocked.

        Blocked scenarios:

        * module is ``removable=False`` (official modules) and
          ``force`` is not set.
        * another running module declares ``name`` in its ``depends``
          or ``integrates``, or any module that still has its tables —
          enabled or disabled — holds a foreign key into the ones about
          to be dropped. Unless ``force``.
        * module has no Alembic ``base_revision`` (Fase A legacy) —
          its schema is part of main linear and cannot be cleanly
          unwound. Always blocked, even with ``force``.
        """
        records = await self._load_existing_records()
        record = records.get(name)
        if record is None:
            raise ModuleOperationError(f"Unknown module: '{name}'")

        if record.state == ModuleState.UNINSTALLED.value:
            return  # no-op

        if record.base_revision is None:
            raise ModuleOperationError(
                f"Module '{name}' has no Alembic branch (legacy in main linear). "
                "Uninstall is not supported in Fase A."
            )

        if not record.removable and not force:
            raise ModuleOperationError(
                f"Module '{name}' is marked removable=False. Use force=True to override."
            )

        dependents = self._schema_dependents(name, records)
        if dependents and not force:
            raise ModuleOperationError(
                f"Cannot uninstall '{name}' — required by: {dependents}. "
                "Uninstall them first or pass force=True."
            )

        record.state = ModuleState.TO_REMOVE.value
        record.last_state_change = datetime.now(UTC)
        record.error_message = None
        record.error_at = None
        await self.db.commit()

        # The processor only runs at the next boot, so without this the
        # module keeps accepting writes into tables it is about to drop.
        module_gate.block(name)

    async def upgrade(self, name: str) -> bool:
        """Mark ``name`` as ``to_upgrade`` when the on-disk manifest
        version differs from the stored version.

        Returns ``True`` if an upgrade was scheduled, ``False`` if the
        module is already at the declared version.
        """
        module = self._require_discovered(name)
        manifest = module.get_manifest()
        record = (
            await self.db.execute(select(ModuleRecord).where(ModuleRecord.name == name))
        ).scalar_one_or_none()
        if record is None:
            raise ModuleOperationError(f"Unknown module: '{name}'")
        if record.state != ModuleState.INSTALLED.value:
            raise ModuleOperationError(
                f"Cannot upgrade '{name}' from state {record.state}. "
                "Only installed modules can be upgraded."
            )

        if record.version == manifest.version:
            return False

        record.state = ModuleState.TO_UPGRADE.value
        record.version = manifest.version
        record.manifest_snapshot = manifest.to_snapshot()
        record.last_state_change = datetime.now(UTC)
        record.error_message = None
        record.error_at = None
        await self.db.commit()
        return True

    # --- Helpers --------------------------------------------------------

    def _require_discovered(self, name: str) -> BaseModule:
        module = module_registry.get(name)
        if module is None:
            raise ModuleOperationError(f"Module '{name}' is not discovered; cannot operate on it.")
        return module

    def _dependency_chain(self, name: str) -> list[str]:
        """Return module + every transitive dep in topo order (deps first)."""
        # Walk the transitive closure first so topological_sort sees the
        # full set of items it needs to order.
        closure: dict[str, BaseModule] = {}
        stack = [name]
        while stack:
            current_name = stack.pop()
            if current_name in closure:
                continue
            module = module_registry.get(current_name)
            if module is None:
                raise ModuleOperationError(
                    f"Missing dependency '{current_name}' (required by '{name}')"
                )
            closure[current_name] = module
            stack.extend(module.dependencies)

        try:
            ordered = topological_sort(
                closure.values(),
                key=lambda m: m.name,
                deps_of=lambda m: m.dependencies,
            )
        except MissingDependencyError as exc:
            raise ModuleOperationError(str(exc)) from exc
        return [m.name for m in ordered]

    # --- Helpers --------------------------------------------------------

    @staticmethod
    def _safe_manifest(module: BaseModule) -> Manifest | None:
        try:
            return module.get_manifest()
        except ManifestError as exc:
            logger.error("Manifest error for %s: %s", module.name, exc)
            return None


async def rediscover_and_reconcile(db: AsyncSession) -> None:
    """Entry point used by the app lifespan.

    Assumes :func:`load_modules` already ran and filled the in-memory
    registry; this just mirrors the current state into ``core_module``.
    """
    svc = ModuleService(db)
    await svc.reconcile_with_db()
    # Also discover here in case `discover_modules()` was not called yet.
    if not module_registry.list_discovered():
        discover_modules()
