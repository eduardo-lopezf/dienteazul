"""Which Apps an App's code may reach into — one rule for every App.

The module guard (``test_module_isolation.py``) lets a module import what
its manifest declares, and looks past imports inside functions and under
``TYPE_CHECKING``. This one is about Apps and looks at every import line:
``IMPORTS`` names, for each App of ``backend/apps.json``, the other Apps
its modules import, and ``REQUIRES`` the ones their manifests ``depends``
on.

Both tables are exact. An App that reaches further fails; so does an App
that reaches less than its entry says, until the entry is tightened — the
tables only ever shrink. The core Apps are where they should be: Agenda
and Patients import nothing, Treatments only the Patients App (no
treatment without a patient), and anything else they need they ask of a
core contract (ADR 0039) or hear in an event (ADR 0042). The optional
Apps are recorded as they stand, to be decoupled in turn.
"""

import re
from pathlib import Path

import pytest

from app.core.plugins.apps import load_app_catalog
from app.core.plugins.registry import module_registry

MODULES_ROOT = Path(__file__).resolve().parents[1] / "app" / "modules"

#: App → the other Apps whose modules its code imports.
IMPORTS: dict[str, set[str]] = {
    "workspace": set(),
    # Core Apps.
    # `calendar_feed` is in here too and imports nothing either: the
    # agenda's appointments reach it as plain data through
    # `AppointmentBook.window` (ADR 0039).
    "agenda": set(),
    "patients": set(),
    "recalls": {"patients", "agenda"},
    "treatments": {"patients"},
    # Optional Apps, as they stand.
    "budgets_payments": {"patients", "treatments", "professionals", "reports"},
    "cash": {"budgets_payments", "professionals"},
    "communications": {"patients", "agenda", "treatments", "budgets_payments", "professionals"},
    "professionals": {"patients", "treatments"},
    "clinical_record": {"patients"},
    "reports": {"patients", "agenda", "treatments", "budgets_payments", "professionals"},
    "ai": set(),
    "data_migration": {
        "patients",
        "agenda",
        "recalls",
        "treatments",
        "budgets_payments",
        # The export reads the professionals it writes out.
        "professionals",
        # ...and consent letters, which belong to the Clinical record.
        "clinical_record",
    },
}

#: App → the other Apps its manifests ``depends`` on. What it merely
#: ``integrates`` is not here: it runs without those (ADR 0037).
REQUIRES: dict[str, set[str]] = {
    **IMPORTS,
    # Budgets and payments integrates Patients, Treatments (catalog,
    # odontogram) and Professionals, and runs with any of them off
    # (`budget/integrations.py`). `billing` also imports `reports` for one
    # endpoint without depending on it — the known debt of
    # `test_module_isolation.KNOWN_VIOLATIONS`.
    "budgets_payments": set(),
    # `record` and `consents` integrate Professionals through
    # `ProfessionalDirectory` and require only the Patients App (media
    # included).
    "clinical_record": {"patients"},
    # Data migration writes into every App it finds running and requires
    # none: whatever belongs to an App that is off is left out.
    "data_migration": set(),
    # Cash, Communications and Reports integrate what they read and require
    # none of it (ADR 0037): each guards the parts that need it.
    "cash": set(),
    "communications": set(),
    "reports": set(),
}

_IMPORT = re.compile(r"\s*(?:from|import)\s+app\.modules\.([a-z_]+)")


def _catalog() -> dict[str, tuple[str, ...]]:
    return {app.name: app.modules for app in load_app_catalog()}


def _owner() -> dict[str, str]:
    return {module: app for app, modules in _catalog().items() for module in modules}


def _imported_apps(app: str) -> dict[str, list[str]]:
    """Other Apps imported by ``app``, each with the lines that do it."""
    members, owner = _catalog()[app], _owner()
    found: dict[str, list[str]] = {}
    for member in members:
        root = MODULES_ROOT / member
        for path in sorted(root.rglob("*.py")):
            if "/migrations/" in str(path):
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                match = _IMPORT.match(line)
                if match and match.group(1) not in members:
                    found.setdefault(owner[match.group(1)], []).append(
                        f"{member}/{path.relative_to(root)}:{number} imports {match.group(1)}"
                    )
    return found


def test_every_app_has_an_entry() -> None:
    assert set(IMPORTS) == set(_catalog()) == set(REQUIRES)


@pytest.mark.parametrize("app", sorted(IMPORTS))
def test_an_app_imports_only_the_apps_it_is_allowed(app: str) -> None:
    imported = _imported_apps(app)

    beyond = {other: lines for other, lines in imported.items() if other not in IMPORTS[app]}
    assert not beyond, "\n".join(line for lines in beyond.values() for line in lines)

    unused = IMPORTS[app] - set(imported)
    assert not unused, f"{app} no longer imports {sorted(unused)} — tighten IMPORTS"


@pytest.mark.parametrize("app", sorted(REQUIRES))
def test_an_app_requires_only_the_apps_it_is_allowed(app: str) -> None:
    owner = _owner()
    manifests = {m.manifest["name"]: m.manifest for m in module_registry.list_discovered()}
    required = {
        owner[dependency]
        for member in _catalog()[app]
        for dependency in manifests[member].get("depends", [])
        if owner[dependency] != app
    }

    assert required <= REQUIRES[app], f"{app} now requires {sorted(required - REQUIRES[app])}"
    unused = REQUIRES[app] - required
    assert not unused, f"{app} no longer requires {sorted(unused)} — tighten REQUIRES"
