"""``apps.json`` groups modules into Apps and switches them for the whole
deployment (ADR 0036, ADR 0038)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.auth.permissions import get_role_permissions
from app.core.plugins import apps as apps_mod
from app.core.plugins.apps import (
    ApiStatus,
    AppCatalogError,
    AppDefinition,
    AppTier,
    integrated_modules,
    load_app_catalog,
    modules_disabled_by_app,
    required_modules,
)
from app.core.plugins.db_models import ModuleRecord
from app.core.plugins.loader import discover_modules
from app.core.plugins.registry import module_registry
from app.core.plugins.service import ModuleService, installed_module_names
from app.core.plugins.state import ModuleState

#: ``apps.json`` as it ships, read before any test swaps the file.
SHIPPED_APPS: list[dict] = json.loads(apps_mod.APPS_FILE.read_text(encoding="utf-8"))["apps"]

AGENDA = {
    "name": "agenda",
    "version": "0.1",
    "status": "enabled",
    "modules": ["agenda", "schedules"],
}


@pytest.fixture(autouse=True)
def _seed_registry() -> None:
    if module_registry.list_discovered():
        return
    for module in discover_modules():
        try:
            module_registry.register(module)
        except ValueError:
            pass


@pytest.fixture
def apps_file(tmp_path, monkeypatch) -> Iterator[Callable[[list[dict]], None]]:
    """Swap ``apps.json`` for one the test writes."""
    path = tmp_path / "apps.json"
    monkeypatch.setattr(apps_mod, "APPS_FILE", path)

    def write(apps: list[dict]) -> None:
        path.write_text(json.dumps({"apps": apps}))
        load_app_catalog.cache_clear()

    yield write
    load_app_catalog.cache_clear()


def _app(name: str) -> AppDefinition:
    return next(app for app in load_app_catalog() if app.name == name)


# --- The file that ships --------------------------------------------------


def test_shipped_catalog_names_only_real_modules() -> None:
    for app in load_app_catalog():
        for module in app.modules:
            assert module_registry.is_discovered(module), module


def test_shipped_agenda_groups_agenda_and_schedules_and_is_enabled() -> None:
    agenda = _app("agenda")

    assert agenda.version == "0.1"
    assert agenda.modules == ("agenda", "schedules")
    assert agenda.enabled is True


def test_the_shipped_catalog_holds_back_only_the_ai_app() -> None:
    """`ai` ships disabled, so `copilot` is not mounted.

    It is the App that proves the switch works on a real deployment —
    `docs/apps/ai/README.md` records what goes with it. This assertion
    used to read `frozenset()`, which was true of the catalog as drafted
    and not of the one that shipped.
    """
    assert modules_disabled_by_app() == frozenset({"copilot"})


def test_agenda_requires_nothing_and_integrates_with_the_rest() -> None:
    """No dependency of Agenda is mandatory (ADR 0037)."""
    agenda = _app("agenda")

    assert required_modules(agenda) == []
    assert set(integrated_modules(agenda)) == {
        "patients",
        "professionals",
        "catalog",
        "treatment_plan",
    }


def test_required_modules_are_the_outside_dependencies() -> None:
    # Treatments needs the Patients App and nothing else: budgets, payments,
    # professionals and the agenda are integrations (ADR 0037). `media` is
    # required by the clinical notes, and lives in the Patients App.
    assert set(required_modules(_app("treatments"))) <= set(_app("patients").modules)

    # Nothing the App already contains, and only what is outside it.
    requires = required_modules(_app("professionals"))
    assert "professionals" not in requires
    assert {"media", "catalog"} <= set(requires)


def test_unknown_module_is_refused() -> None:
    with pytest.raises(ValueError, match="not discovered"):
        required_modules(AppDefinition(name="ghost", version="0.1", modules=("nope",)))


# --- Reading the file -----------------------------------------------------


def test_status_must_be_enabled_or_disabled(apps_file) -> None:
    apps_file([{**AGENDA, "status": "paused"}])

    with pytest.raises(AppCatalogError, match="Invalid app entry"):
        load_app_catalog()


def test_a_module_belongs_to_one_app(apps_file) -> None:
    apps_file([AGENDA, {**AGENDA, "name": "other", "modules": ["schedules"]}])

    with pytest.raises(AppCatalogError, match="belongs to both"):
        load_app_catalog()


def test_an_app_is_listed_once(apps_file) -> None:
    apps_file([AGENDA, {**AGENDA, "modules": ["recalls"]}])

    with pytest.raises(AppCatalogError, match="listed twice"):
        load_app_catalog()


def test_an_api_status_must_be_known(apps_file) -> None:
    apps_file([{**AGENDA, "apis": [{"name": "google_calendar", "status": "soon"}]}])

    with pytest.raises(AppCatalogError, match="Invalid app entry"):
        load_app_catalog()


def test_an_api_is_listed_once_per_app(apps_file) -> None:
    api = {"name": "google_calendar", "status": "planned"}
    apps_file([{**AGENDA, "apis": [api, api]}])

    with pytest.raises(AppCatalogError, match="lists an API twice"):
        load_app_catalog()


WORKSPACE = {
    "name": "workspace",
    "version": "0.1",
    "tier": "base",
    "status": "enabled",
    "modules": [],
}


def test_the_base_app_cannot_be_disabled(apps_file) -> None:
    """The App everything else runs on (ADR 0043)."""
    apps_file([{**WORKSPACE, "status": "disabled"}, AGENDA])

    with pytest.raises(AppCatalogError, match="base App and cannot be disabled"):
        load_app_catalog()


def test_there_is_one_base_app(apps_file) -> None:
    apps_file([WORKSPACE, {**WORKSPACE, "name": "other"}])

    with pytest.raises(AppCatalogError, match="more than one base App"):
        load_app_catalog()


def test_only_the_base_app_groups_no_modules(apps_file) -> None:
    apps_file([WORKSPACE, {**AGENDA, "modules": []}])

    with pytest.raises(AppCatalogError, match="groups no modules"):
        load_app_catalog()


def test_an_app_without_a_tier_is_optional(apps_file) -> None:
    apps_file([AGENDA])

    assert _app("agenda").tier is AppTier.OPTIONAL


def test_shipped_catalog_opens_with_the_workspace_and_names_the_core_apps() -> None:
    catalog = load_app_catalog()

    assert catalog[0].name == "workspace"
    assert catalog[0].tier is AppTier.BASE and catalog[0].enabled
    assert catalog[0].modules == ()
    core = {app.name for app in catalog if app.tier is AppTier.CORE}
    # Professionals too: every practice has its professional (ADR 0058).
    assert core == {"agenda", "patients", "treatments", "professionals"}


def test_every_module_belongs_to_an_app() -> None:
    """A module nobody's App lists could never be switched off with one,
    and the catalog would describe less than the product."""
    listed = {module for app in load_app_catalog() for module in app.modules}
    discovered = {module.manifest["name"] for module in module_registry.list_discovered()}
    assert discovered - listed == set()


def test_shipped_agenda_lists_google_calendar_as_planned() -> None:
    """Listed, not switchable: there is no integration behind it yet."""
    apis = {api.name: api.status for api in _app("agenda").apis}

    assert apis == {"google_calendar": ApiStatus.PLANNED}


# --- A disabled App -------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_app_holds_its_modules_back_without_touching_their_state(
    db_session: AsyncSession, apps_file
) -> None:
    await ModuleService(db_session).reconcile_with_db()
    apps_file([{**AGENDA, "status": "disabled"}])

    running = await installed_module_names(db_session)

    assert not running & {"agenda", "schedules"}
    # Everything else, including what depends on agenda, still runs.
    assert {"patients", "recalls", "treatment_plan", "notifications"} <= running
    # And the database was not told anything: flipping the flag back is
    # all it takes to bring them back.
    for name in ("agenda", "schedules"):
        record = (
            await db_session.execute(select(ModuleRecord).where(ModuleRecord.name == name))
        ).scalar_one()
        assert record.state == ModuleState.INSTALLED.value


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_runtime")
async def test_boot_with_agenda_disabled_leaves_the_rest_running(
    db_session: AsyncSession, apps_file
) -> None:
    from app.main import lifespan

    apps_file([{**AGENDA, "status": "disabled"}])

    app = FastAPI()
    async with lifespan(app):
        paths = list(app.openapi()["paths"])
        dentist = get_role_permissions("dentist")

    assert not any(p.startswith("/api/v1/agenda") for p in paths)
    assert not any(p.startswith("/api/v1/schedules") for p in paths)
    assert not module_registry.is_installed("agenda")
    assert not any(perm.startswith("agenda.") for perm in dentist)

    # Modules that depend on agenda are untouched.
    for dependent in ("recalls", "treatment_plan", "clinical_notes", "reports"):
        assert module_registry.is_installed(dependent), dependent
    assert any(p.startswith("/api/v1/patients") for p in paths)
    assert any(p.startswith("/api/v1/recalls") for p in paths)


# --- An App switched off with the one it requires (ADR 0053) ---------------

PATIENTS = {
    "name": "patients",
    "version": "0.1",
    "status": "enabled",
    "modules": ["patients", "patients_clinical", "patient_timeline", "media"],
}
CLINICAL_RECORD = {
    "name": "clinical_record",
    "version": "0.1",
    "status": "enabled",
    "modules": ["record", "consents"],
    "requires_apps": ["patients"],
}
TREATMENTS = {
    "name": "treatments",
    "version": "0.1",
    "status": "enabled",
    "modules": ["catalog", "treatment_plan", "odontogram", "periodontogram", "clinical_notes"],
}


def test_the_shipped_clinical_record_goes_off_with_patients() -> None:
    assert _app("clinical_record").requires_apps == ("patients",)
    assert _app("clinical_record").enabled and _app("clinical_record").held_back_by is None
    # Nobody else declared it: dependents keep running, as ADR 0038 left it.
    others = [app.name for app in load_app_catalog() if app.requires_apps]
    assert others == ["clinical_record"]


def test_patients_off_takes_the_clinical_record_and_nothing_else(apps_file) -> None:
    apps_file([{**PATIENTS, "status": "disabled"}, CLINICAL_RECORD, TREATMENTS])

    record = _app("clinical_record")
    assert not record.enabled and record.held_back_by == "patients"
    assert not _app("patients").enabled and _app("patients").held_back_by is None
    # Treatments depends on patients too, and did not ask to go with it.
    assert _app("treatments").enabled
    assert modules_disabled_by_app() == {
        "patients",
        "patients_clinical",
        "patient_timeline",
        "media",
        "record",
        "consents",
    }
    # Not an edit waiting for a restart: the file and what runs agree.
    assert apps_mod.statuses_on_disk()["clinical_record"] is record.status


def test_the_clinical_record_off_leaves_patients_running(apps_file) -> None:
    apps_file([PATIENTS, {**CLINICAL_RECORD, "status": "disabled"}, TREATMENTS])

    assert _app("patients").enabled
    # Disabled by the file, not held back by anything.
    assert not _app("clinical_record").enabled
    assert _app("clinical_record").held_back_by is None
    assert modules_disabled_by_app() == {"record", "consents"}


def test_going_off_with_a_required_app_carries_through_a_chain(apps_file) -> None:
    apps_file(
        [
            {**PATIENTS, "status": "disabled"},
            CLINICAL_RECORD,
            {**TREATMENTS, "requires_apps": ["clinical_record"]},
        ]
    )
    assert _app("treatments").held_back_by == "clinical_record"
    assert not _app("treatments").enabled


@pytest.mark.parametrize("required", ["nowhere", "clinical_record"])
def test_an_app_requires_only_other_listed_apps(apps_file, required: str) -> None:
    apps_file([PATIENTS, {**CLINICAL_RECORD, "requires_apps": [required]}])
    with pytest.raises(AppCatalogError, match="requires"):
        load_app_catalog()


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_runtime")
async def test_boot_without_the_clinical_record_leaves_patients_whole(
    db_session: AsyncSession, apps_file
) -> None:
    """Patients integrates with the Clinical record; it does not need it."""
    from app.main import lifespan

    apps_file(
        [
            entry if entry["name"] != "clinical_record" else {**entry, "status": "disabled"}
            for entry in SHIPPED_APPS
        ]
    )

    app = FastAPI()
    async with lifespan(app):
        paths = list(app.openapi()["paths"])
        dentist = get_role_permissions("dentist")

    assert not any(p.startswith(("/api/v1/record", "/api/v1/consents")) for p in paths)
    assert not module_registry.is_installed("record")
    assert not module_registry.is_installed("consents")
    assert not any(perm.startswith(("record.", "consents.")) for perm in dentist)

    # The patient's file is all there: demographics, history, the ASA
    # class, the health questionnaire, documents.
    for prefix in (
        "/api/v1/patients",
        "/api/v1/patients_clinical/patients/{patient_id}/asa",
        "/api/v1/patients_clinical/patients/{patient_id}/questionnaires",
        "/api/v1/patients_clinical/patients/{patient_id}/alerts",
        "/api/v1/media",
    ):
        assert any(p.startswith(prefix) for p in paths), prefix
    assert "patients_clinical.asa.write" in dentist


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_runtime")
async def test_boot_without_patients_mounts_neither(db_session: AsyncSession, apps_file) -> None:
    from app.main import lifespan

    apps_file(
        [
            entry if entry["name"] != "patients" else {**entry, "status": "disabled"}
            for entry in SHIPPED_APPS
        ]
    )

    app = FastAPI()
    async with lifespan(app):
        paths = list(app.openapi()["paths"])

    gone = ("/api/v1/patients", "/api/v1/record", "/api/v1/consents")
    assert not any(p.startswith(gone) for p in paths)
    for name in ("patients", "patients_clinical", "record", "consents"):
        assert not module_registry.is_installed(name), name
    # Treatments did not ask to go with Patients (ADR 0038).
    assert module_registry.is_installed("treatment_plan")


# --- HTTP -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_apps_endpoint_lists_the_catalog(
    client: AsyncClient, auth_headers: dict, test_clinic: Clinic
) -> None:
    response = await client.get("/api/v1/apps", headers=auth_headers)

    assert response.status_code == 200
    agenda = next(app for app in response.json()["data"] if app["name"] == "agenda")
    assert agenda["version"] == "0.1"
    assert agenda["enabled"] is True
    assert agenda["tier"] == "core"
    assert agenda["modules"] == ["agenda", "schedules"]
    assert agenda["requires"] == []
    assert "patients" in agenda["integrates"]
    assert agenda["apis"] == [{"name": "google_calendar", "status": "planned"}]


@pytest.mark.asyncio
async def test_active_modules_leave_out_a_disabled_app(
    client: AsyncClient,
    auth_headers: dict,
    test_clinic: Clinic,
    db_session: AsyncSession,
    apps_file,
) -> None:
    """The sidebar is built from this response: no entry for the agenda."""
    await ModuleService(db_session).reconcile_with_db()
    apps_file([{**AGENDA, "status": "disabled"}])

    response = await client.get("/api/v1/modules/-/active", headers=auth_headers)

    names = {module["name"] for module in response.json()["data"]}
    assert not names & {"agenda", "schedules"}
    assert "patients" in names


@pytest.mark.asyncio
async def test_apps_endpoint_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/apps")

    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_an_edit_waiting_for_a_restart_is_reported(
    client: AsyncClient, auth_headers: dict, test_clinic: Clinic, apps_file
) -> None:
    """`apps.json` is read at boot. An edit made since then is not in
    effect — and the screen must not show the App as if nothing had been
    written."""
    apps_file([WORKSPACE, AGENDA])
    load_app_catalog()  # what "boot" read

    # Edited on disk afterwards; the cached catalog is what still runs.
    path = apps_mod.APPS_FILE
    path.write_text(json.dumps({"apps": [WORKSPACE, {**AGENDA, "status": "disabled"}]}))

    response = await client.get("/api/v1/apps", headers=auth_headers)
    apps = {app["name"]: app for app in response.json()["data"]}

    assert apps["agenda"]["enabled"] is True
    assert apps["agenda"]["pending_enabled"] is False
    assert apps["workspace"]["pending_enabled"] is None
