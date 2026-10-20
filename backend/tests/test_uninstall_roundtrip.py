"""Integration test for the hardened module uninstall pipeline (issue #56).

Two scenarios:

* **Schedules roundtrip** — drives Alembic via subprocess to prove that
  downgrading the schedules branch all the way back (``schedules@-N``,
  ``N`` = revisions the branch owns — ``schedules@base`` would cascade
  into every other branch's shared ancestor, see
  ``processor._downgrade_target_for``) drops only schedules tables and
  leaves every other module's schema untouched, and that
  ``alembic upgrade schedules@head`` restores them. This exercises the
  combined Bug #1 (right downgrade target) + Bug #2 (branch isolation)
  fix.
* **Migration import roundtrip** — the same, for the module that is
  actually uninstalled in anger: a clinic imports its old program once
  and then switches the App off. Its eight staging tables are read from
  its own models rather than listed here (see ``_declared_tables``).
* **pg_dump hard-fail** — monkeypatches ``pg_dump`` out of ``PATH`` and
  asserts that ``PendingProcessor._dump_tables`` raises ``RuntimeError``
  instead of returning ``None`` silently.

Marked ``alembic_roundtrip`` and excluded from the default pytest run
(same policy as ``test_alembic_roundtrip``).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import asyncpg
import pytest

from app.config import settings
from app.core.plugins.loader import discover_modules
from app.core.plugins.processor import _count_owned_revisions

pytestmark = pytest.mark.alembic_roundtrip

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

SCHEDULES_TABLES = {
    "clinic_weekly_schedules",
    "clinic_overrides",
    "professional_weekly_schedules",
    "professional_overrides",
    "schedule_shifts",
}

PERIODONTOGRAM_TABLES = {
    "periodontogram_snapshots",
    "periodontogram_teeth",
    "periodontogram_sites",
}


def _declared_tables(module_name: str) -> set[str]:
    """The tables a module's own models declare, asked of the module.

    The two sets above are written out because they are short and old.
    ``migration_import`` owns eight tables and is under active work, and
    a list copied into a test is exactly the kind that goes stale while
    still passing — the same reason this file computes
    ``_count_owned_revisions`` instead of hardcoding it.

    It covers what the models declare. A table some migration creates
    with no model behind it would go unwatched here, which under-asserts
    rather than fails wrongly.
    """
    module = next(m for m in discover_modules() if m.name == module_name)
    tables = {model.__tablename__ for model in module.get_models()}
    assert tables, f"{module_name} declares no models"
    return tables


def _alembic(*args: str) -> None:
    subprocess.run(
        ["alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=BACKEND_ROOT,
        check=True,
    )


def _dsn() -> str:
    return settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


async def _list_tables_async() -> set[str]:
    conn = await asyncpg.connect(_dsn())
    try:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name != 'alembic_version'"
        )
        return {row["table_name"] for row in rows}
    finally:
        await conn.close()


def _list_tables() -> set[str]:
    return asyncio.run(_list_tables_async())


def test_schedules_uninstall_roundtrip_is_branch_scoped() -> None:
    """install → uninstall → reinstall drops only schedules' tables."""
    _alembic("upgrade", "heads")
    before = _list_tables()
    assert SCHEDULES_TABLES.issubset(before), (
        f"expected schedules tables at heads; missing: {SCHEDULES_TABLES - before}"
    )
    baseline_non_schedules = before - SCHEDULES_TABLES

    # Branch-scoped downgrade — the uninstall path the processor now uses.
    # ``<label>@-N`` walks N steps back on the labelled branch; N must be
    # every revision the branch owns (computed the same way
    # ``_downgrade_target_for`` does), not a hardcoded count that goes
    # stale the moment a second revision lands.
    _alembic("downgrade", f"schedules@-{_count_owned_revisions('schedules')}")

    after_down = _list_tables()
    assert SCHEDULES_TABLES.isdisjoint(after_down), (
        f"schedules tables survived downgrade: {SCHEDULES_TABLES & after_down}"
    )
    assert baseline_non_schedules <= after_down, (
        "downgrade leaked into other modules; missing tables: "
        f"{baseline_non_schedules - after_down}"
    )

    # Reinstall via the same branch head the processor uses for install.
    _alembic("upgrade", "schedules@head")
    after_up = _list_tables()
    assert before <= after_up, (
        f"reinstall did not restore every table; missing: {before - after_up}"
    )


def test_periodontogram_uninstall_roundtrip_is_branch_scoped() -> None:
    """install → uninstall → reinstall drops only periodontogram's tables.

    Mirrors the schedules round-trip: the partial unique index protecting
    the single-draft invariant must also be re-created cleanly.
    """
    _alembic("upgrade", "heads")
    before = _list_tables()
    assert PERIODONTOGRAM_TABLES.issubset(before), (
        f"expected periodontogram tables at heads; missing: {PERIODONTOGRAM_TABLES - before}"
    )
    baseline_non_periodontogram = before - PERIODONTOGRAM_TABLES

    _alembic("downgrade", f"periodontogram@-{_count_owned_revisions('periodontogram')}")

    after_down = _list_tables()
    assert PERIODONTOGRAM_TABLES.isdisjoint(after_down), (
        f"periodontogram tables survived downgrade: {PERIODONTOGRAM_TABLES & after_down}"
    )
    assert baseline_non_periodontogram <= after_down, (
        "downgrade leaked into other modules; missing tables: "
        f"{baseline_non_periodontogram - after_down}"
    )

    _alembic("upgrade", "periodontogram@head")
    after_up = _list_tables()
    assert before <= after_up, (
        f"reinstall did not restore every table; missing: {before - after_up}"
    )


def test_migration_import_uninstall_roundtrip_is_branch_scoped() -> None:
    """install → uninstall → reinstall drops only migration_import's tables.

    The module whose uninstall is not hypothetical: a clinic imports its
    previous program once and switches the App off afterwards, and what
    is left behind belongs to `patients`, `payments` and the rest — this
    branch owns only the staging of the import itself (its CLAUDE.md
    says so; this is what holds it to it).
    """
    tables = _declared_tables("migration_import")

    _alembic("upgrade", "heads")
    before = _list_tables()
    assert tables.issubset(before), (
        f"expected migration_import tables at heads; missing: {tables - before}"
    )
    baseline_others = before - tables

    _alembic("downgrade", f"migration_import@-{_count_owned_revisions('migration_import')}")

    after_down = _list_tables()
    assert tables.isdisjoint(after_down), (
        f"migration_import tables survived downgrade: {tables & after_down}"
    )
    # The point of the module: the imported rows are other modules', and
    # they stay. Nothing here may take a patient, a payment or an
    # appointment with it.
    assert baseline_others <= after_down, (
        f"downgrade leaked into other modules; missing tables: {baseline_others - after_down}"
    )

    _alembic("upgrade", "migration_import@head")
    after_up = _list_tables()
    assert before <= after_up, (
        f"reinstall did not restore every table; missing: {before - after_up}"
    )


def test_dump_tables_hard_fails_when_pg_dump_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without pg_dump on PATH the backup must raise, not silently skip."""
    from app.core.plugins import processor as processor_module

    monkeypatch.setattr(processor_module, "BACKUP_ROOT", tmp_path / "backups")

    def _raise_not_found(*_args, **_kwargs):
        raise FileNotFoundError("pg_dump")

    monkeypatch.setattr(processor_module.subprocess, "run", _raise_not_found)

    # Build a processor with a dummy session factory — the method under
    # test never opens a session.
    proc = processor_module.PendingProcessor(session_factory=lambda: None)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="pg_dump not available"):
        asyncio.run(proc._dump_tables("schedules", ["clinic_weekly_schedules"]))


def test_dump_tables_hard_fails_on_empty_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A zero-byte dump counts as a silent corruption and must raise."""
    from app.core.plugins import processor as processor_module

    monkeypatch.setattr(processor_module, "BACKUP_ROOT", tmp_path / "backups")

    def _fake_run(args, *, stdout, check, timeout=None):  # noqa: ARG001
        # stdout is the open file handle; write nothing → zero bytes.
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(processor_module.subprocess, "run", _fake_run)

    proc = processor_module.PendingProcessor(session_factory=lambda: None)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="empty backup"):
        asyncio.run(proc._dump_tables("schedules", ["clinic_weekly_schedules"]))
