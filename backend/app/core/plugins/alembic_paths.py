"""Helpers shared between :mod:`alembic.env`, the plugin service, and tests.

Kept outside the ``alembic/env.py`` script because that file is executed
by Alembic at import time and is awkward to import from tests.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseModule

logger = logging.getLogger(__name__)


def discover_version_locations(
    main_linear: Path,
    modules_root: Path,
) -> list[str]:
    """Return the main linear path + every existing per-module branch.

    A module is treated as contributing a branch when it has a directory
    ``<modules_root>/<name>/migrations/versions/``. Directories whose
    name starts with ``_`` are skipped so tests can stash scratch data
    under ``<modules_root>/__scratch__/`` without polluting real
    discovery.

    This is intentionally filesystem-only — the function runs during
    Alembic bootstrap when ``core_module`` may not exist yet, and in
    offline (``--sql``) mode where no database connection is available.
    """
    locations: list[str] = [str(main_linear)]

    if modules_root.is_dir():
        for module_dir in sorted(modules_root.iterdir()):
            if not module_dir.is_dir() or module_dir.name.startswith("_"):
                continue
            branch = module_dir / "migrations" / "versions"
            if branch.is_dir():
                locations.append(str(branch))

    return locations


def _module_versions_dir(module: BaseModule) -> Path | None:
    spec = importlib.util.find_spec(type(module).__module__)
    if spec is None or spec.origin is None:
        return None
    versions_dir = (Path(spec.origin).parent / "migrations" / "versions").resolve()
    return versions_dir if versions_dir.is_dir() else None


def _alembic_cfg_path() -> Path:
    return Path(__file__).resolve().parents[3] / "alembic.ini"


def _load_script_directory():
    cfg_path = _alembic_cfg_path()
    if not cfg_path.is_file():
        return None
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    try:
        return ScriptDirectory.from_config(Config(str(cfg_path)))
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("Could not load Alembic ScriptDirectory: %s", exc)
        return None


def _revisions_in_dir(versions_dir: Path) -> list[str]:
    """Revisions whose file lives in ``versions_dir``, newest first.

    ``walk_revisions`` descends from every head towards base, so the
    order it yields is the branch read from its tip downwards.
    """
    script = _load_script_directory()
    if script is None:
        return []

    revisions: list[str] = []
    for rev in script.walk_revisions():
        rev_path_str = getattr(rev, "path", None)
        if not rev_path_str:
            continue
        try:
            rev_dir = Path(rev_path_str).resolve().parent
        except (OSError, ValueError):
            continue
        if rev_dir == versions_dir:
            revisions.append(rev.revision)
    return revisions


def _head_in_dir(versions_dir: Path) -> str | None:
    """Newest revision whose file lives in ``versions_dir``."""
    revisions = _revisions_in_dir(versions_dir)
    return revisions[0] if revisions else None


def core_versions_dir() -> Path:
    """Directory holding the core linear chain's revisions."""
    return (Path(__file__).resolve().parents[3] / "alembic" / "versions").resolve()


def resolve_core_head() -> str | None:
    """Tip of the core linear chain — the revisions the app cannot boot without.

    Boot upgrades *this* revision, never ``heads``: ``heads`` includes
    every module branch found on disk and so re-creates the tables of a
    module that was uninstalled (audit S1). Module branches are brought
    to head by :class:`~app.core.plugins.processor.PendingProcessor`,
    which knows which modules are installed.
    """
    versions_dir = core_versions_dir()
    if not versions_dir.is_dir():
        return None
    return _head_in_dir(versions_dir)


def resolve_module_branch_head(module: BaseModule) -> str | None:
    """Return the tip revision of ``module``'s own Alembic branch, if any.

    Modules that ship a ``migrations/versions`` directory alongside their
    code are the "owners" of every revision file inside it. The head of
    the module's branch is the module-owned revision that comes first
    when Alembic walks the full graph from ``heads`` to ``base`` (i.e.
    the latest descendant of every module revision).

    Returns ``None`` when the module lives in the legacy main linear
    chain (no per-module migrations dir), the migrations dir exists but
    is empty, or the Alembic graph can't be loaded.
    """
    versions_dir = _module_versions_dir(module)
    if versions_dir is None:
        return None
    return _head_in_dir(versions_dir)


def revisions_at_or_below(heads: set[str]) -> set[str]:
    """Every revision at or below ``heads`` in the Alembic graph.

    ``alembic_version`` stores **heads only**. A revision another
    module's chain descends from has run and is still absent from that
    table — ``pt_0001`` is, because ``bil_0001`` hangs off it, and
    ``med_0002`` is, because the chain continues through it — so asking
    whether a revision is *in* the table answers the wrong question.
    Ancestry is the question.

    Empty when the graph cannot be loaded or ``heads`` names nothing the
    code knows: the caller is then left with the heads themselves, the
    narrower reading, which errs towards re-running a migration rather
    than towards skipping one.
    """
    script = _load_script_directory()
    if script is None:
        return set()

    known: list[str] = []
    for head in heads:
        try:
            if script.get_revision(head) is not None:
                known.append(head)
        except Exception:  # noqa: BLE001 — a revision this code does not ship
            continue
    if not known:
        return set()

    try:
        return {rev.revision for rev in script.iterate_revisions(tuple(known), "base")}
    except Exception:  # pragma: no cover — defensive
        logger.warning("Could not walk the Alembic graph below %s", sorted(known))
        return set()


def module_branch_revisions(module: BaseModule) -> list[str]:
    """Every revision on ``module``'s own branch, newest first.

    The head alone cannot say *how far* a branch got. Reconcile needs the
    whole list to correct a record that claims a revision
    ``alembic_version`` never ran down to the newest one it did.

    Empty for a module with no branch of its own (legacy main-linear).
    """
    versions_dir = _module_versions_dir(module)
    if versions_dir is None:
        return []
    return _revisions_in_dir(versions_dir)


def module_branch_is_isolated(module: BaseModule) -> bool:
    """True when the module's revisions form a self-contained branch.

    A module is branch-isolated when no revision outside its own
    ``migrations/versions/`` directory descends from any of the
    module's revisions. Practically: running
    ``alembic downgrade <module>@base`` rolls back only the module's
    tables, never touching another module's migrations.

    Modules without their own migrations directory (legacy main-linear)
    are considered NOT isolated — they are the reason Bug #2 exists.
    """
    versions_dir = _module_versions_dir(module)
    if versions_dir is None:
        return False

    script = _load_script_directory()
    if script is None:
        return False

    owned: set[str] = set()
    for rev in script.walk_revisions():
        rev_path_str = getattr(rev, "path", None)
        if not rev_path_str:
            continue
        try:
            rev_dir = Path(rev_path_str).resolve().parent
        except (OSError, ValueError):
            continue
        if rev_dir == versions_dir:
            owned.add(rev.revision)

    if not owned:
        return False

    for rev in script.walk_revisions():
        if rev.revision in owned:
            continue
        down = rev.down_revision
        parents: tuple[str, ...]
        if down is None:
            parents = ()
        elif isinstance(down, str):
            parents = (down,)
        else:
            parents = tuple(down)
        if any(p in owned for p in parents):
            return False
    return True
