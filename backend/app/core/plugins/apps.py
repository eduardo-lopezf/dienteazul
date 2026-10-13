"""The App catalog.

An App is what a clinic chooses; a module is what the code is made of.
One App groups the modules that only make sense together — "Agenda" is
``agenda`` plus ``schedules`` — and carries its own version, which moves
independently of theirs (ADR 0036).

The catalog is ``backend/apps.json``, one file for the whole deployment.
Each App is ``enabled`` or ``disabled`` there, and a disabled App's
modules are not mounted, whatever ``core_module.state`` says about them
(ADR 0038). Nothing else changes: their tables, their data and their
install state stay as they are, so flipping the flag back restores them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import cache
from pathlib import Path

from .registry import module_registry
from .topology import topological_sort

APPS_FILE = Path(__file__).resolve().parents[3] / "apps.json"


class AppStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class AppTier(StrEnum):
    """How much of every workspace an App is.

    ``base`` is the one App everything else runs on — the clinic, its
    people, the shell and settings. It is the core and the host app, not a
    group of modules, so it lists none, and it cannot be disabled (ADR 0043).
    ``core`` Apps are set up for every workspace; ``optional`` ones are
    chosen — unless the catalog makes one core for a clinic's account
    tier (``core_for_tiers``).
    """

    BASE = "base"
    CORE = "core"
    OPTIONAL = "optional"


class ApiStatus(StrEnum):
    """Where an App's connection to an outside service stands.

    ``planned`` is listed and nothing more: there is no code behind it
    yet, so it cannot be switched on by editing the file.
    """

    PLANNED = "planned"
    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class ApiDefinition:
    """An outside service an App can connect to (ADR 0040).

    Only the name and the switch live here. Credentials never do: this
    file is committed.
    """

    name: str
    status: ApiStatus


class AppCatalogError(ValueError):
    """``apps.json`` is malformed."""


@dataclass(frozen=True, slots=True)
class AppDefinition:
    name: str
    version: str
    modules: tuple[str, ...]
    status: AppStatus = AppStatus.ENABLED
    apis: tuple[ApiDefinition, ...] = ()
    tier: AppTier = AppTier.OPTIONAL
    #: Account tiers (``AccountTier`` values) whose clinics always have
    #: this App, though it is optional for the rest. Professionals is one:
    #: a clinic has several, a single professional's practice has none.
    core_for_tiers: tuple[str, ...] = ()
    #: Apps this one is switched off with (``requires_apps`` in the file).
    #: Off when any of them is off — the exception to "dependents keep
    #: running", declared App by App (ADR 0053).
    requires_apps: tuple[str, ...] = ()
    #: The required App whose being off switched this one off. None when
    #: the file itself says ``disabled``, or when the App runs.
    held_back_by: str | None = None

    @property
    def enabled(self) -> bool:
        return self.status is AppStatus.ENABLED


@cache
def load_app_catalog() -> tuple[AppDefinition, ...]:
    """``apps.json`` as it was when the process started.

    Cached for the life of the process: what is mounted was decided from
    this file at boot, so a later edit must not be reported as if it had
    taken effect. It does at the next restart.
    """
    return read_app_catalog()


def read_app_catalog() -> tuple[AppDefinition, ...]:
    """Read and validate ``apps.json`` as it is on disk right now.

    For whoever needs the file itself rather than what is running — the
    operator's console lists the Apps from it on every request, so an
    edit shows there at once. What is *mounted* is still
    :func:`load_app_catalog`.
    """
    raw = json.loads(APPS_FILE.read_text(encoding="utf-8"))

    apps: list[AppDefinition] = []
    owner: dict[str, str] = {}
    for entry in raw["apps"]:
        try:
            app = AppDefinition(
                name=entry["name"],
                version=entry["version"],
                modules=tuple(entry["modules"]),
                status=AppStatus(entry["status"]),
                tier=AppTier(entry.get("tier", AppTier.OPTIONAL)),
                core_for_tiers=tuple(entry.get("core_for_tiers", ())),
                requires_apps=tuple(entry.get("requires_apps", ())),
                apis=tuple(
                    ApiDefinition(name=api["name"], status=ApiStatus(api["status"]))
                    for api in entry.get("apis", ())
                ),
            )
        except (KeyError, ValueError) as exc:
            raise AppCatalogError(f"Invalid app entry in {APPS_FILE.name}: {entry!r}") from exc

        if app.tier is AppTier.BASE and not app.enabled:
            raise AppCatalogError(
                f"App '{app.name}' is the base App and cannot be disabled in {APPS_FILE.name}"
            )
        if app.tier is AppTier.BASE and any(other.tier is AppTier.BASE for other in apps):
            raise AppCatalogError(f"{APPS_FILE.name} declares more than one base App")
        if app.tier is not AppTier.BASE and not app.modules:
            raise AppCatalogError(f"App '{app.name}' groups no modules in {APPS_FILE.name}")
        api_names = [api.name for api in app.apis]
        if len(api_names) != len(set(api_names)):
            raise AppCatalogError(f"App '{app.name}' lists an API twice in {APPS_FILE.name}")
        if any(app.name == other.name for other in apps):
            raise AppCatalogError(f"App '{app.name}' is listed twice in {APPS_FILE.name}")
        for module in app.modules:
            if module in owner:
                raise AppCatalogError(
                    f"Module '{module}' belongs to both '{owner[module]}' and '{app.name}'"
                )
            owner[module] = app.name
        apps.append(app)

    names = {app.name for app in apps}
    for app in apps:
        unknown = [other for other in app.requires_apps if other not in names or other == app.name]
        if unknown:
            raise AppCatalogError(
                f"App '{app.name}' requires {unknown}, which {APPS_FILE.name} does not list"
            )
    return _switch_off_with_required(apps)


def _switch_off_with_required(apps: list[AppDefinition]) -> tuple[AppDefinition, ...]:
    """An App goes off with the Apps it declares it cannot run without.

    Repeated until nothing changes, so it carries through a chain: C off
    takes B, and B takes A. An App the file already disables is left as
    written — nothing held it back.
    """
    resolved = {app.name: app for app in apps}
    changed = True
    while changed:
        changed = False
        for app in list(resolved.values()):
            if not app.enabled:
                continue
            missing = next(
                (other for other in app.requires_apps if not resolved[other].enabled), None
            )
            if missing is not None:
                resolved[app.name] = replace(app, status=AppStatus.DISABLED, held_back_by=missing)
                changed = True
    return tuple(resolved[app.name] for app in apps)


def statuses_on_disk() -> dict[str, AppStatus]:
    """Each App's status as ``apps.json`` says it *now*.

    Not cached, unlike :func:`load_app_catalog`: the difference between
    the two is a change that is written and waiting for a restart. The
    Apps screen says so, instead of showing a running App as if the edit
    had not been made. A file that no longer parses yields nothing — the
    next boot will refuse it, loudly.
    """
    try:
        # Read the way the boot reads it, so an App switched off with the
        # one it requires is not reported as an edit waiting for a restart.
        return {app.name: app.status for app in read_app_catalog()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def modules_disabled_by_app() -> frozenset[str]:
    """Modules that must not be mounted because their App is disabled —
    by the file, or with an App it requires (ADR 0053)."""
    return frozenset(
        module for app in load_app_catalog() if not app.enabled for module in app.modules
    )


def integrated_modules(app: AppDefinition) -> list[str]:
    """Modules outside ``app`` that its own modules integrate with (ADR 0037).

    Optional, unlike :func:`required_modules`: the App works without
    them and links to them when they run.
    """
    found: list[str] = []
    for name in app.modules:
        module = module_registry.get(name)
        if module is None:
            raise ValueError(f"App '{app.name}' needs module '{name}', which is not discovered")
        for other in module.get_manifest().integrates:
            if other not in app.modules and other not in found:
                found.append(other)
    return found


def required_modules(app: AppDefinition) -> list[str]:
    """Modules outside ``app`` that its own modules depend on, dependencies first.

    Transitive: what would have to be enabled alongside the App for its
    modules to run.
    """
    closure: dict[str, list[str]] = {}
    stack = list(app.modules)
    while stack:
        name = stack.pop()
        if name in closure:
            continue
        module = module_registry.get(name)
        if module is None:
            raise ValueError(f"App '{app.name}' needs module '{name}', which is not discovered")
        closure[name] = module.dependencies
        stack.extend(closure[name])

    ordered = topological_sort(closure, key=lambda name: name, deps_of=lambda name: closure[name])
    return [name for name in ordered if name not in app.modules]


def mandatory_apps(account_tier: str) -> list[str]:
    """Apps a clinic of ``account_tier`` always has, in catalog order: the
    base App, the core ones, and those the catalog makes core for that
    tier. An App the deployment has switched off is nobody's."""
    return [
        app.name
        for app in load_app_catalog()
        if app.enabled and (app.tier is not AppTier.OPTIONAL or account_tier in app.core_for_tiers)
    ]


def required_apps(app: AppDefinition) -> list[str]:
    """Other Apps that own a module ``app`` cannot run without."""
    owner = {module: other.name for other in load_app_catalog() for module in other.modules}
    return list(dict.fromkeys(owner[module] for module in required_modules(app)))


def modules_outside(apps: list[str] | None) -> frozenset[str]:
    """Modules a clinic does not have, given the Apps chosen for it.

    ``None`` — nobody chose for the clinic — means it has every App, so
    nothing is outside. Otherwise it is every module of every App that is
    not on the list. What the deployment itself has switched off is a
    separate matter (:func:`modules_disabled_by_app`).
    """
    if apps is None:
        return frozenset()
    return frozenset(
        module for app in load_app_catalog() if app.name not in apps for module in app.modules
    )
