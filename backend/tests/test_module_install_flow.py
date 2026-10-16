"""Tests for ModuleService state transitions (enable/disable/install/uninstall/upgrade)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plugins.db_models import ModuleRecord
from app.core.plugins.gate import module_gate
from app.core.plugins.loader import discover_modules
from app.core.plugins.registry import module_registry
from app.core.plugins.service import ModuleOperationError, ModuleService
from app.core.plugins.state import ModuleState


def _seed_registry() -> None:
    if module_registry.list_discovered():
        return
    for module in discover_modules():
        try:
            module_registry.register(module)
        except ValueError:
            pass


async def _reconcile(db_session: AsyncSession) -> None:
    _seed_registry()
    await ModuleService(db_session).reconcile_with_db()


@pytest.mark.asyncio
async def test_uninstall_blocked_for_non_removable_module(db_session: AsyncSession) -> None:
    """Non-removable modules must reject uninstall even when they ship an
    Alembic branch — ``billing`` has its own ``bil_0001`` branch that the
    service auto-resolves during reconcile."""
    await _reconcile(db_session)

    svc = ModuleService(db_session)
    with pytest.raises(ModuleOperationError, match="removable=False"):
        await svc.uninstall("billing")


@pytest.mark.asyncio
async def test_uninstall_blocked_for_legacy_module_without_branch(
    db_session: AsyncSession,
) -> None:
    """Modules whose migrations live in the main linear chain (no
    per-module ``migrations/versions`` dir) have ``base_revision=None``
    even after reconcile, so uninstall falls back to the legacy guard."""
    await _reconcile(db_session)

    # Force a pristine state by wiping base_revision and marking removable.
    from app.core.plugins.db_models import ModuleRecord

    billing = (
        await db_session.execute(select(ModuleRecord).where(ModuleRecord.name == "billing"))
    ).scalar_one()
    billing.base_revision = None
    billing.removable = True
    await db_session.commit()

    svc = ModuleService(db_session)
    with pytest.raises(ModuleOperationError, match="no Alembic branch"):
        await svc.uninstall("billing")


@pytest.mark.asyncio
async def test_uninstall_blocked_by_reverse_dependency(
    db_session: AsyncSession,
) -> None:
    await _reconcile(db_session)

    # Fake a branch revision + removable=True so the only block is the
    # reverse dep from notifications.
    budget = (
        await db_session.execute(select(ModuleRecord).where(ModuleRecord.name == "budget"))
    ).scalar_one()
    budget.base_revision = "fake_base"
    budget.removable = True
    await db_session.commit()

    svc = ModuleService(db_session)
    with pytest.raises(ModuleOperationError, match="required by"):
        await svc.uninstall("budget")


@pytest.mark.asyncio
async def test_install_already_installed_is_noop(
    db_session: AsyncSession,
) -> None:
    await _reconcile(db_session)

    svc = ModuleService(db_session)
    scheduled = await svc.install("patients")
    assert scheduled == []


@pytest.mark.asyncio
async def test_install_schedules_dependency_chain(
    db_session: AsyncSession,
) -> None:
    await _reconcile(db_session)

    # Mark billing as uninstalled to simulate a fresh install of it and
    # its chain: billing depends on payments, which depends on budget.
    # `catalog` is only integrated (ADR 0037) and is not pulled in.
    chain = ("budget", "payments", "billing")
    for name in (*chain, "catalog"):
        row = (
            await db_session.execute(select(ModuleRecord).where(ModuleRecord.name == name))
        ).scalar_one()
        row.state = ModuleState.UNINSTALLED.value
    await db_session.commit()

    svc = ModuleService(db_session)
    scheduled = await svc.install("billing")

    assert set(chain) <= set(scheduled)
    assert "catalog" not in scheduled
    # Dependency-first order.
    assert scheduled.index("budget") < scheduled.index("payments") < scheduled.index("billing")

    # All three now marked to_install.
    for name in chain:
        row = (
            await db_session.execute(select(ModuleRecord).where(ModuleRecord.name == name))
        ).scalar_one()
        assert row.state == ModuleState.TO_INSTALL.value


@pytest.mark.asyncio
async def test_upgrade_noop_when_versions_match(
    db_session: AsyncSession,
) -> None:
    await _reconcile(db_session)

    svc = ModuleService(db_session)
    assert await svc.upgrade("billing") is False


@pytest.mark.asyncio
async def test_upgrade_marks_to_upgrade_when_version_diverges(
    db_session: AsyncSession,
) -> None:
    await _reconcile(db_session)

    billing = (
        await db_session.execute(select(ModuleRecord).where(ModuleRecord.name == "billing"))
    ).scalar_one()
    billing.version = "0.0.0"
    await db_session.commit()

    svc = ModuleService(db_session)
    assert await svc.upgrade("billing") is True

    refreshed = (
        await db_session.execute(select(ModuleRecord).where(ModuleRecord.name == "billing"))
    ).scalar_one()
    assert refreshed.state == ModuleState.TO_UPGRADE.value
    assert refreshed.version != "0.0.0"  # bumped to manifest version


# --- Enable / disable (ADR 0035) ------------------------------------------


async def _get(db_session: AsyncSession, name: str) -> ModuleRecord:
    return (
        await db_session.execute(select(ModuleRecord).where(ModuleRecord.name == name))
    ).scalar_one()


@pytest.mark.asyncio
async def test_module_without_auto_install_starts_disabled(db_session: AsyncSession) -> None:
    """Never ``uninstalled``: its tables are there, it just does not run."""
    await _reconcile(db_session)

    verifactu = await _get(db_session, "verifactu")
    assert verifactu.state == ModuleState.DISABLED.value
    assert verifactu.installed_at is None
    # Recorded at head so the processor keeps the branch migrated.
    assert verifactu.applied_revision is not None


@pytest.mark.asyncio
async def test_reconcile_turns_never_installed_into_disabled(db_session: AsyncSession) -> None:
    """Databases that predate ADR 0035 hold these rows as ``uninstalled``."""
    await _reconcile(db_session)

    verifactu = await _get(db_session, "verifactu")
    verifactu.state = ModuleState.UNINSTALLED.value
    await db_session.commit()

    await ModuleService(db_session).reconcile_with_db()

    assert (await _get(db_session, "verifactu")).state == ModuleState.DISABLED.value


@pytest.mark.asyncio
async def test_reconcile_leaves_a_real_uninstall_alone(db_session: AsyncSession) -> None:
    """The processor's uninstall clears ``applied_revision``: tables are gone."""
    await _reconcile(db_session)

    recalls = await _get(db_session, "recalls")
    recalls.state = ModuleState.UNINSTALLED.value
    recalls.applied_revision = None
    await db_session.commit()

    await ModuleService(db_session).reconcile_with_db()

    assert (await _get(db_session, "recalls")).state == ModuleState.UNINSTALLED.value


@pytest.mark.asyncio
async def test_disable_keeps_the_record_and_its_revisions(db_session: AsyncSession) -> None:
    await _reconcile(db_session)
    before = await _get(db_session, "copilot")
    applied, installed_at = before.applied_revision, before.installed_at

    try:
        await ModuleService(db_session).disable("copilot")

        after = await _get(db_session, "copilot")
        assert after.state == ModuleState.DISABLED.value
        # Nothing about the schema or its history is forgotten.
        assert after.applied_revision == applied
        assert after.installed_at == installed_at
        # Still mounted until the restart, so it must stop answering now.
        assert module_gate.is_blocked("copilot")
    finally:
        module_gate.clear()


@pytest.mark.asyncio
async def test_disable_ignores_removable_false(db_session: AsyncSession) -> None:
    """``removable`` guards data. Disabling loses none, so it does not apply."""
    await _reconcile(db_session)
    assert (await _get(db_session, "reports")).removable is False

    try:
        await ModuleService(db_session).disable("reports")
        assert (await _get(db_session, "reports")).state == ModuleState.DISABLED.value
    finally:
        module_gate.clear()


@pytest.mark.asyncio
async def test_disable_blocked_while_an_enabled_module_depends_on_it(
    db_session: AsyncSession,
) -> None:
    await _reconcile(db_session)

    with pytest.raises(ModuleOperationError, match="required by"):
        await ModuleService(db_session).disable("agenda")

    assert (await _get(db_session, "agenda")).state == ModuleState.INSTALLED.value
    assert not module_gate.is_blocked("agenda")


@pytest.mark.asyncio
async def test_enable_brings_back_a_disabled_module_with_its_dependencies(
    db_session: AsyncSession,
) -> None:
    await _reconcile(db_session)

    # verifactu depends on billing; both off.
    for name in ("verifactu", "billing"):
        (await _get(db_session, name)).state = ModuleState.DISABLED.value
    await db_session.commit()

    scheduled = await ModuleService(db_session).enable("verifactu")

    assert scheduled.index("billing") < scheduled.index("verifactu")
    for name in ("verifactu", "billing"):
        assert (await _get(db_session, name)).state == ModuleState.TO_INSTALL.value


# --- Integrations (ADR 0037) ----------------------------------------------


async def _declare_integration(db_session: AsyncSession, module: str, target: str) -> None:
    """Make ``module`` integrate with ``target`` in its stored manifest.

    Synthetic on purpose: every module the real manifests integrate with
    also has hard dependents, which would decide the outcome first.
    """
    record = await _get(db_session, module)
    record.manifest_snapshot = {**record.manifest_snapshot, "depends": [], "integrates": [target]}
    await db_session.commit()


@pytest.mark.asyncio
async def test_disable_is_not_blocked_by_a_module_that_only_integrates(
    db_session: AsyncSession,
) -> None:
    await _reconcile(db_session)
    await _declare_integration(db_session, "reports", "copilot")

    try:
        await ModuleService(db_session).disable("copilot")
        assert (await _get(db_session, "copilot")).state == ModuleState.DISABLED.value
    finally:
        module_gate.clear()


@pytest.mark.asyncio
async def test_uninstall_is_blocked_by_a_running_module_that_integrates(
    db_session: AsyncSession,
) -> None:
    """Dropping tables is another matter: an integration expects them."""
    await _reconcile(db_session)
    await _declare_integration(db_session, "reports", "copilot")

    with pytest.raises(ModuleOperationError, match="required by.*reports"):
        await ModuleService(db_session).uninstall("copilot")


@pytest.mark.asyncio
async def test_uninstall_is_blocked_by_a_disabled_module_holding_foreign_keys(
    db_session: AsyncSession,
) -> None:
    """A disabled module still has its tables (ADR 0035). ``agenda`` holds
    foreign keys into ``professionals``, so it blocks even when off."""
    await _reconcile(db_session)
    agenda = await _get(db_session, "agenda")
    agenda.state = ModuleState.DISABLED.value
    await db_session.commit()

    with pytest.raises(ModuleOperationError, match="required by.*agenda"):
        await ModuleService(db_session).uninstall("professionals")


@pytest.mark.asyncio
async def test_uninstall_is_not_blocked_by_a_disabled_module_without_foreign_keys(
    db_session: AsyncSession,
) -> None:
    """``migration_import`` lists ``recalls`` in ``depends`` and starts
    disabled, but none of its tables point at recalls': declaring is not
    holding."""
    await _reconcile(db_session)
    assert (await _get(db_session, "migration_import")).state == ModuleState.DISABLED.value

    try:
        await ModuleService(db_session).uninstall("recalls")
        assert (await _get(db_session, "recalls")).state == ModuleState.TO_REMOVE.value
    finally:
        module_gate.clear()
