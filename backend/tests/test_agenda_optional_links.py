"""Agenda keeps booking while the Apps it links to are off (ADR 0037, ADR 0038).

A module not being mounted is what "off" means here, whichever way it
got there — ``apps.json`` or ``modules disable``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.plugins.apps import load_app_catalog
from app.core.plugins.registry import module_registry
from app.modules.agenda.integrations import (
    PATIENTS_UNAVAILABLE,
    PROFESSIONALS_UNAVAILABLE,
    TREATMENTS_UNAVAILABLE,
    treatments_available,
)
from app.modules.agenda.kanban_service import KanbanDayService
from app.modules.agenda.models import Appointment, Cabinet
from app.modules.agenda.presenter import present, present_one
from app.modules.agenda.schemas import AppointmentResponse
from app.modules.agenda.service import AppointmentService
from app.modules.patients.models import Patient
from app.modules.professionals.models import Professional

START = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)


def _switch_off(*names: str):
    was_active = [name for name in names if module_registry.is_installed(name)]
    for name in names:
        module_registry.deactivate(name)
    yield
    for name in was_active:
        module_registry.activate(name)


@pytest.fixture
def treatments_off():
    yield from _switch_off("treatment_plan")


@pytest.fixture
def patients_off():
    yield from _switch_off("patients")


@pytest.fixture
def professionals_off():
    yield from _switch_off("professionals")


@pytest.fixture
def everything_off():
    yield from _switch_off("patients", "professionals", "treatment_plan")


async def _world(db: AsyncSession) -> dict[str, UUID]:
    clinic = Clinic(
        id=uuid4(),
        name="Optional Clinic",
        tax_id="B00000077",
        address={"city": "Madrid"},
        settings={},
        account_tier="clinic",
    )
    db.add(clinic)
    await db.flush()
    cabinet = Cabinet(id=uuid4(), clinic_id=clinic.id, name="Gabinete 1", color="#3B82F6")
    patient = Patient(id=uuid4(), clinic_id=clinic.id, first_name="Juan", last_name="Paciente")
    professional = Professional(
        id=uuid4(),
        clinic_id=clinic.id,
        first_name="Dentist",
        last_name="User",
        professional_type="dentist",
        is_active=True,
    )
    db.add_all([cabinet, patient, professional])
    await db.commit()
    return {
        "clinic_id": clinic.id,
        "patient_id": patient.id,
        "professional_id": professional.id,
        "cabinet_id": cabinet.id,
    }


def _payload(world: dict[str, UUID], **extra) -> dict:
    return {
        "patient_id": world["patient_id"],
        "professional_id": world["professional_id"],
        "cabinet_id": world["cabinet_id"],
        "start_time": START,
        "end_time": START + timedelta(minutes=30),
        **extra,
    }


def test_treatments_is_its_own_app() -> None:
    treatments = next(app for app in load_app_catalog() if app.name == "treatments")

    assert treatments.modules == (
        "catalog",
        "treatment_plan",
        "odontogram",
        "periodontogram",
        "clinical_notes",
    )
    assert treatments.enabled is True


@pytest.mark.asyncio
async def test_appointment_is_booked_without_treatments_while_the_app_is_off(
    db_session: AsyncSession, treatments_off
) -> None:
    world = await _world(db_session)
    assert treatments_available() is False

    appointment = await AppointmentService.create_appointment(
        db_session, world["clinic_id"], _payload(world)
    )
    await db_session.commit()

    assert isinstance(appointment, Appointment)
    assert appointment.status == "scheduled"


@pytest.mark.asyncio
async def test_new_treatment_links_are_refused_while_the_app_is_off(
    db_session: AsyncSession, treatments_off
) -> None:
    world = await _world(db_session)

    with pytest.raises(ValueError, match="Treatments cannot be assigned"):
        await AppointmentService.create_appointment(
            db_session, world["clinic_id"], _payload(world, planned_item_ids=[uuid4()])
        )


@pytest.mark.asyncio
async def test_treatment_links_cannot_be_added_on_update_while_the_app_is_off(
    db_session: AsyncSession, treatments_off
) -> None:
    world = await _world(db_session)
    appointment = await AppointmentService.create_appointment(
        db_session, world["clinic_id"], _payload(world)
    )
    await db_session.commit()

    with pytest.raises(ValueError, match=TREATMENTS_UNAVAILABLE):
        await AppointmentService.update_appointment(
            db_session, appointment, {"planned_item_ids": [uuid4()]}
        )


@pytest.mark.asyncio
async def test_stored_treatment_links_are_not_shown_while_the_app_is_off(
    db_session: AsyncSession, treatments_off
) -> None:
    """Kept, not deleted, not listed: they come back when the App does."""
    world = await _world(db_session)
    appointment = await AppointmentService.create_appointment(
        db_session, world["clinic_id"], _payload(world)
    )
    await db_session.commit()

    response = await present_one(db_session, appointment)

    assert response.treatments == []


# --- Patients and professionals -------------------------------------------


def test_patients_and_professionals_are_apps() -> None:
    apps = {app.name: app for app in load_app_catalog()}

    assert apps["patients"].modules == (
        "patients",
        "patients_clinical",
        "patient_timeline",
        "media",
    )
    assert apps["professionals"].modules == ("professionals", "commissions")
    assert apps["patients"].enabled and apps["professionals"].enabled


@pytest.mark.asyncio
async def test_a_professional_is_still_required_while_the_app_runs(
    db_session: AsyncSession,
) -> None:
    """Nothing changes for a clinic that has Professionals: the link is the default."""
    world = await _world(db_session)
    payload = _payload(world)
    del payload["professional_id"]

    with pytest.raises(ValueError, match="A professional is required"):
        await AppointmentService.create_appointment(db_session, world["clinic_id"], payload)


@pytest.mark.asyncio
async def test_appointment_with_nothing_linked_when_every_app_is_off(
    db_session: AsyncSession, everything_off
) -> None:
    world = await _world(db_session)

    appointment = await AppointmentService.create_appointment(
        db_session,
        world["clinic_id"],
        {
            "title": "Mantenimiento del sillón",
            "start_time": START,
            "end_time": START + timedelta(minutes=30),
        },
    )
    await db_session.commit()

    assert appointment.patient_id is None
    assert appointment.professional_id is None
    assert appointment.title == "Mantenimiento del sillón"

    response = await present_one(db_session, appointment)
    assert response.title == "Mantenimiento del sillón"
    assert response.patient is None and response.professional is None


@pytest.mark.asyncio
async def test_new_patient_link_is_refused_while_patients_is_off(
    db_session: AsyncSession, patients_off
) -> None:
    world = await _world(db_session)

    with pytest.raises(ValueError, match=PATIENTS_UNAVAILABLE):
        await AppointmentService.create_appointment(db_session, world["clinic_id"], _payload(world))


@pytest.mark.asyncio
async def test_new_professional_link_is_refused_while_professionals_is_off(
    db_session: AsyncSession, professionals_off
) -> None:
    world = await _world(db_session)

    with pytest.raises(ValueError, match=PROFESSIONALS_UNAVAILABLE):
        await AppointmentService.create_appointment(db_session, world["clinic_id"], _payload(world))


@pytest.mark.asyncio
async def test_links_hide_while_the_app_is_off_and_return_with_it(
    db_session: AsyncSession,
) -> None:
    """The whole promise in one place: kept, hidden, restored."""
    world = await _world(db_session)
    await AppointmentService.create_appointment(db_session, world["clinic_id"], _payload(world))
    await db_session.commit()

    async def listed() -> AppointmentResponse:
        rows, _ = await AppointmentService.list_appointments(db_session, world["clinic_id"])
        return (await present(db_session, world["clinic_id"], rows))[0]

    module_registry.deactivate("patients")
    module_registry.deactivate("professionals")
    try:
        hidden = await listed()
        assert hidden.patient_id is None and hidden.patient is None
        assert hidden.professional_id is None and hidden.professional is None
    finally:
        module_registry.activate("patients")
        module_registry.activate("professionals")

    restored = await listed()
    assert restored.patient_id == world["patient_id"]
    assert restored.patient is not None and restored.patient.first_name == "Juan"
    assert restored.professional_id == world["professional_id"]
    assert restored.professional is not None


@pytest.mark.asyncio
async def test_kanban_offers_no_professionals_while_the_app_is_off(
    db_session: AsyncSession, professionals_off
) -> None:
    world = await _world(db_session)

    snapshot = await KanbanDayService.snapshot(db_session, world["clinic_id"], START.date())

    assert snapshot["professionals"] == []


@pytest.mark.asyncio
async def test_events_carry_no_professional_for_an_unassigned_appointment(
    db_session: AsyncSession, everything_off, monkeypatch
) -> None:
    """The payload used to say ``"None"`` — a string — for a missing id."""
    from app.modules.agenda import service as service_mod

    published: list[dict] = []
    monkeypatch.setattr(
        service_mod.event_bus,
        "publish_after_commit",
        lambda db, event, payload: published.append(payload),
    )
    world = await _world(db_session)

    await AppointmentService.create_appointment(
        db_session,
        world["clinic_id"],
        {"start_time": START, "end_time": START + timedelta(minutes=30)},
    )

    assert published and published[0]["professional_id"] is None
    assert published[0]["patient_id"] is None
