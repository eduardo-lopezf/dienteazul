"""Mapper foundations: :class:`MapperContext` and :class:`MappingResolver`.

Both live in a single module so concrete mappers can keep their imports
tight (``from .base import MapperContext, MappingResolver``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plugins.registry import module_registry

from ..models import EntityMapping, ImportWarning


def running(*modules: str) -> bool:
    """Whether every one of ``modules`` is running here (ADR 0037)."""
    return all(module_registry.is_installed(module) for module in modules)


if TYPE_CHECKING:
    from ..dpmf import DpmfHandle


_SKIP_SUFFIX = ".__skipped__"
_SKIP_SENTINEL_TABLE = "__skipped__"
_SKIP_SENTINEL_ID = UUID("00000000-0000-0000-0000-000000000000")


class MappingResolver:
    """Read / write the ``entity_mappings`` table.

    All FK resolution between DPMF entities goes through this object —
    mappers never use canonical UUIDs directly as Diente Azul row IDs.

    Memoisation is per-instance (one resolver per job), bounded by the
    number of distinct entity_type+canonical_uuid pairs in the file.

    "Skipped" sidecar: mappers that decide to drop a canonical row (e.g.
    a non-clinical Gesdén entry, an appointment with no schedule) can
    call :meth:`mark_skipped` so a re-execute short-circuits via
    :meth:`was_skipped` instead of re-running the side effects
    (duplicate Treatment / PlannedTreatmentItem rows, redundant warning
    emissions). The skipped marks live in ``entity_mappings`` under a
    suffixed entity_type so :meth:`get` never returns them.
    """

    def __init__(self, db: AsyncSession, clinic_id: UUID, job_id: UUID) -> None:
        self._db = db
        self._clinic_id = clinic_id
        self._job_id = job_id
        self._cache: dict[tuple[str, str], UUID] = {}
        self._skipped_cache: set[tuple[str, str]] = set()
        # Set by :meth:`preload_cache` so :meth:`get` knows whether a
        # cache miss is authoritative (preloaded → guaranteed unmapped)
        # or just a missing entry that still warrants a DB read.
        self._cache_warm: bool = False

    async def get(self, entity_type: str, canonical_uuid: str) -> UUID | None:
        """Return the Diente Azul row id mapped to ``(entity_type, canonical_uuid)``.

        Scoped to ``clinic_id`` so two clinics importing the same DPMF
        do not see each other's resolutions.
        """
        key = (entity_type, canonical_uuid)
        if key in self._cache:
            return self._cache[key]
        if self._cache_warm:
            # Bulk preload already populated the cache for this
            # clinic; a miss here means the entity has never been
            # mapped. Skip the DB round-trip — saves ~5 ms × 1 M
            # idempotency checks on a re-run.
            return None
        result = await self._db.execute(
            select(EntityMapping.dienteazul_id).where(
                EntityMapping.clinic_id == self._clinic_id,
                EntityMapping.entity_type == entity_type,
                EntityMapping.source_canonical_uuid == canonical_uuid,
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            self._cache[key] = row
        return row

    async def preload_cache(self) -> None:
        """Load every ``entity_mappings`` row for this clinic into memory.

        Called once at the start of ``_run_pipeline``. After this:
        - :meth:`get` cache hits resolve in O(1) instead of a DB
          round-trip, so a re-run that short-circuits every entity
          finishes in seconds instead of minutes.
        - :meth:`was_skipped` reads the cache for ``<type>.__skipped__``
          rows the same way.

        Trade-off: one big SELECT + the in-memory dict size (~1 M rows
        × ~80 bytes = ~80 MB on the biggest real Gesdén imports). Still
        well below the backend container's memory budget and pays
        itself back after the first ~10 K rows of any re-run.
        """
        result = await self._db.execute(
            select(
                EntityMapping.entity_type,
                EntityMapping.source_canonical_uuid,
                EntityMapping.dienteazul_id,
            ).where(EntityMapping.clinic_id == self._clinic_id)
        )
        loaded = 0
        for entity_type, canonical_uuid, dienteazul_id in result.all():
            if entity_type.endswith(_SKIP_SUFFIX):
                base = entity_type[: -len(_SKIP_SUFFIX)]
                self._skipped_cache.add((base, canonical_uuid))
            else:
                self._cache[(entity_type, canonical_uuid)] = dienteazul_id
            loaded += 1
        self._cache_warm = True
        return loaded  # type: ignore[return-value]

    async def set(
        self,
        entity_type: str,
        canonical_uuid: str,
        source_system: str,
        dienteazul_table: str,
        dienteazul_id: UUID,
    ) -> None:
        """Persist the mapping. Idempotent — second call for the same
        ``(entity_type, canonical_uuid)`` is a no-op (cache hit or
        existing row in DB) so a re-execute never trips the UNIQUE
        constraint on ``entity_mappings``."""
        key = (entity_type, canonical_uuid)
        if key in self._cache:
            return
        if not self._cache_warm:
            existing = await self._db.execute(
                select(EntityMapping.dienteazul_id).where(
                    EntityMapping.clinic_id == self._clinic_id,
                    EntityMapping.entity_type == entity_type,
                    EntityMapping.source_canonical_uuid == canonical_uuid,
                )
            )
            row = existing.scalar_one_or_none()
            if row is not None:
                self._cache[key] = row
                return
        mapping = EntityMapping(
            clinic_id=self._clinic_id,
            job_id=self._job_id,
            source_system=source_system,
            entity_type=entity_type,
            source_canonical_uuid=canonical_uuid,
            dienteazul_table=dienteazul_table,
            dienteazul_id=dienteazul_id,
        )
        self._db.add(mapping)
        self._cache[key] = dienteazul_id

    async def mapping_table(self, entity_type: str, canonical_uuid: str) -> str | None:
        """Return the ``dienteazul_table`` recorded for this mapping.

        Lets a downstream mapper tell apart canonicals that landed as,
        say, ``treatments`` vs ``clinical_notes`` without inventing a
        new sidecar per shape. Not cached — call sparingly (mainly the
        ``DebtMapper`` checking whether the source applied_treatment
        was routed to a Treatment or to an administrative note).
        Returns ``None`` if the mapping does not exist.
        """
        result = await self._db.execute(
            select(EntityMapping.dienteazul_table).where(
                EntityMapping.clinic_id == self._clinic_id,
                EntityMapping.entity_type == entity_type,
                EntityMapping.source_canonical_uuid == canonical_uuid,
            )
        )
        return result.scalar_one_or_none()

    async def mark_skipped(
        self,
        entity_type: str,
        canonical_uuid: str,
        source_system: str,
    ) -> None:
        """Record that this canonical was intentionally dropped.

        Subsequent calls to :meth:`was_skipped` for the same key return
        ``True`` so re-executes can short-circuit. Stored under a
        suffixed entity_type so ordinary :meth:`get` lookups are not
        polluted with the sentinel.
        """
        key = (entity_type, canonical_uuid)
        if key in self._skipped_cache:
            return
        mapping = EntityMapping(
            clinic_id=self._clinic_id,
            job_id=self._job_id,
            source_system=source_system,
            entity_type=f"{entity_type}{_SKIP_SUFFIX}",
            source_canonical_uuid=canonical_uuid,
            dienteazul_table=_SKIP_SENTINEL_TABLE,
            dienteazul_id=_SKIP_SENTINEL_ID,
        )
        self._db.add(mapping)
        self._skipped_cache.add(key)

    async def was_skipped(self, entity_type: str, canonical_uuid: str) -> bool:
        key = (entity_type, canonical_uuid)
        if key in self._skipped_cache:
            return True
        if self._cache_warm:
            return False
        result = await self._db.execute(
            select(EntityMapping.id).where(
                EntityMapping.clinic_id == self._clinic_id,
                EntityMapping.entity_type == f"{entity_type}{_SKIP_SUFFIX}",
                EntityMapping.source_canonical_uuid == canonical_uuid,
            )
        )
        if result.scalar_one_or_none() is not None:
            self._skipped_cache.add(key)
            return True
        return False

    async def resolve_actor(self, source_user_uuid: Any, fallback: UUID) -> UUID:
        """Resolve a DPMF ``user_uuid`` to a destination ``users.id``.

        Falls back to ``fallback`` (typically ``ctx.created_by``) when
        the canonical uuid is missing, malformed, or points at a user
        the importer didn't land. This preserves the original
        Gesdén audit trail when possible without breaking the FK
        constraint when the source row is incomplete.
        """
        if not source_user_uuid:
            return fallback
        resolved = await self.get("user", str(source_user_uuid))
        return resolved or fallback


@dataclass
class ProfessionalFilterOptions:
    """Knobs that gate which source professionals stay agenda-visible.

    Applied by :class:`mappers.professional.ProfessionalMapper`. Every
    filtered row is still imported as a ``User`` (so historical FKs
    from appointments / treatments / budgets / payments keep resolving)
    but with ``is_active=False`` and ``ClinicMembership.role='assistant'``
    — that combination removes the row from the agenda's clinician list
    (`backend/app/core/auth/router.py` filters on role + is_active).

    Defaults mirror :class:`ExecuteRequest`. A ``None`` instance on the
    context disables all filtering (legacy execute paths and tests).
    """

    min_activity_months: int = 24
    exclude_agenda_orphans: bool = True
    exclude_inactive_in_source: bool = True
    exclude_non_clinical_roles: bool = False


@dataclass
class MapperContext:
    """Per-job context handed to every mapper invocation."""

    db: AsyncSession
    clinic_id: UUID
    job_id: UUID
    resolver: MappingResolver
    import_fiscal_compliance: bool
    created_by: UUID  # The admin who launched the import; used as actor for created_by FKs.
    professional_filters: ProfessionalFilterOptions | None = field(default=None)
    # Optional reference to the open DPMF handle. Populated by the
    # service orchestrator inside ``_run_pipeline``. Mappers that need
    # to peek at sibling rows (e.g. the applied_treatment shadow-pairing
    # pre-pass) read it; the rest can ignore it. Tests and other call
    # sites that don't open a DPMF leave it ``None``.
    handle: DpmfHandle | None = field(default=None)
    # ``client_uuid`` → list of patient_ids linked to that client.
    # Populated by ``PatientClientLinkMapper`` (Gesdén's ``PacCli`` is
    # M:N) and read by ``PaymentMapper`` to split a ``PagoCli`` across
    # every family member instead of attributing the whole amount to
    # the first patient mapped. Empty by default so test paths that
    # bypass the link mapper just see the 1:1 fallback.
    client_to_patients: dict[str, list[UUID]] = field(default_factory=dict)


async def account_email_for_import(
    ctx: MapperContext,
    *,
    email: str,
    canonical_uuid: str,
    entity_type: str,
    source_id: str,
) -> str:
    """The address this import may open a staff account under.

    ``users.email`` is unique across the deployment and an account is
    global (ADR 0057), so looking a person up by email reaches accounts
    belonging to clinics the importer has nothing to do with. Both the
    user and professional mappers did exactly that and then added a
    membership, which silently made another tenant's staff into this
    clinic's — and gave them its patient data.

    So: the address is returned unchanged when it is free, or when it
    already belongs to somebody who is this clinic's staff (the
    idempotent re-run every mapper relies on). When it belongs to an
    account outside this clinic, a synthetic local address is returned
    instead and a warning is recorded. The import still brings the
    person in, under an account of this clinic's own — the outside one
    is not read, not written, and not attached.

    Derived from ``canonical_uuid``, so a re-run lands on the same
    address and the import stays idempotent.
    """
    from app.core.auth.models import ClinicMembership, User

    owner = await ctx.db.scalar(select(User.id).where(User.email == email))
    if owner is None:
        return email

    member_here = await ctx.db.scalar(
        select(ClinicMembership.id).where(
            ClinicMembership.user_id == owner,
            ClinicMembership.clinic_id == ctx.clinic_id,
        )
    )
    if member_here is not None:
        return email

    substitute = f"migrado+{entity_type}-{canonical_uuid[:12]}@dental-bridge.local"
    ctx.db.add(
        ImportWarning(
            job_id=ctx.job_id,
            entity_type=entity_type,
            source_id=source_id,
            severity="warn",
            code=f"{entity_type}.email_belongs_to_another_clinic",
            message=(
                f"{email} is already an account outside this clinic, so it was not "
                f"reused. The person was imported under {substitute}; set their real "
                "address once the other clinic releases it."
            ),
        )
    )
    return substitute


class Mapper(Protocol):
    """Structural interface every concrete mapper satisfies."""

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None: ...
