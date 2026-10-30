"""The lists a clinic works through.

The rule every one of them shares is the one worth pinning: somebody
already booked is not on any list. A queue that keeps offering a patient
who has an appointment on Thursday gets ignored, and then the real rows
go unworked too.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.agenda.models import Appointment
from app.modules.patients.models import Patient
from app.modules.reports import actionable

LISTS = [
    "/api/v1/reports/actionable/owes-not-booked",
    "/api/v1/reports/actionable/accepted-not-booked",
    "/api/v1/reports/actionable/no-visit",
]


async def _patient(db: AsyncSession, clinic: Clinic, *, last_name: str) -> Patient:
    patient = Patient(
        id=uuid4(),
        clinic_id=clinic.id,
        first_name="Test",
        last_name=last_name,
        phone="+34 600 000 000",
    )
    db.add(patient)
    await db.flush()
    return patient


async def _appointment(
    db: AsyncSession, clinic: Clinic, patient: Patient, *, start: datetime, status: str
) -> Appointment:
    appointment = Appointment(
        id=uuid4(),
        clinic_id=clinic.id,
        patient_id=patient.id,
        start_time=start,
        end_time=start + timedelta(minutes=30),
        status=status,
    )
    db.add(appointment)
    await db.flush()
    return appointment


@pytest.mark.asyncio
@pytest.mark.parametrize("path", LISTS)
async def test_every_list_answers_and_says_whether_it_was_cut(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic, path: str
) -> None:
    response = await client.get(path, headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert isinstance(data["rows"], list)
    # A screen must be able to say "there are more" rather than imply the
    # queue is finished.
    assert data["truncated"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("path", LISTS)
async def test_every_list_needs_its_permission(
    client: AsyncClient, auth_headers: dict[str, str], path: str
) -> None:
    """These rows are names, phones and debts — their own grant."""
    response = await client.get(path, headers=auth_headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_future_appointment_takes_a_patient_off_the_lists(
    db_session: AsyncSession, test_clinic: Clinic
) -> None:
    booked = await _patient(db_session, test_clinic, last_name="Booked")
    await _appointment(
        db_session,
        test_clinic,
        booked,
        start=datetime.now(UTC) + timedelta(days=3),
        status="scheduled",
    )
    await db_session.flush()

    ids = await actionable._patient_ids_with_future_appointments(db_session, test_clinic.id)
    assert booked.id in ids


@pytest.mark.asyncio
async def test_a_cancelled_future_appointment_does_not_count_as_booked(
    db_session: AsyncSession, test_clinic: Clinic
) -> None:
    """A cancelled slot is precisely the patient who needs calling."""
    patient = await _patient(db_session, test_clinic, last_name="Cancelled")
    await _appointment(
        db_session,
        test_clinic,
        patient,
        start=datetime.now(UTC) + timedelta(days=3),
        status="cancelled",
    )
    await db_session.flush()

    ids = await actionable._patient_ids_with_future_appointments(db_session, test_clinic.id)
    assert patient.id not in ids


@pytest.mark.asyncio
async def test_a_past_appointment_does_not_count_as_booked(
    db_session: AsyncSession, test_clinic: Clinic
) -> None:
    patient = await _patient(db_session, test_clinic, last_name="Past")
    await _appointment(
        db_session,
        test_clinic,
        patient,
        start=datetime.now(UTC) - timedelta(days=3),
        status="completed",
    )
    await db_session.flush()

    ids = await actionable._patient_ids_with_future_appointments(db_session, test_clinic.id)
    assert patient.id not in ids


@pytest.mark.asyncio
async def test_a_patient_seen_long_ago_is_on_the_no_visit_list(
    db_session: AsyncSession, test_clinic: Clinic
) -> None:
    lapsed = await _patient(db_session, test_clinic, last_name="Lapsed")
    await _appointment(
        db_session,
        test_clinic,
        lapsed,
        start=datetime.now(UTC) - timedelta(days=500),
        status="completed",
    )
    recent = await _patient(db_session, test_clinic, last_name="Recent")
    await _appointment(
        db_session,
        test_clinic,
        recent,
        start=datetime.now(UTC) - timedelta(days=20),
        status="completed",
    )
    await db_session.flush()

    rows = await actionable.no_visit_in_months(db_session, test_clinic.id, 12)
    found = {row.patient_id for row in rows}
    assert lapsed.id in found
    assert recent.id not in found


@pytest.mark.asyncio
async def test_only_a_visit_that_happened_counts_as_being_seen(
    db_session: AsyncSession, test_clinic: Clinic
) -> None:
    """A recent appointment the patient did not attend is not a visit."""
    patient = await _patient(db_session, test_clinic, last_name="NoShow")
    await _appointment(
        db_session,
        test_clinic,
        patient,
        start=datetime.now(UTC) - timedelta(days=500),
        status="completed",
    )
    await _appointment(
        db_session,
        test_clinic,
        patient,
        start=datetime.now(UTC) - timedelta(days=10),
        status="no_show",
    )
    await db_session.flush()

    rows = await actionable.no_visit_in_months(db_session, test_clinic.id, 12)
    assert patient.id in {row.patient_id for row in rows}


@pytest.mark.asyncio
async def test_the_rows_carry_what_to_do_with_them(
    db_session: AsyncSession, test_clinic: Clinic
) -> None:
    """A name with no phone number is not an actionable row."""
    patient = await _patient(db_session, test_clinic, last_name="Callable")
    await _appointment(
        db_session,
        test_clinic,
        patient,
        start=datetime.now(UTC) - timedelta(days=500),
        status="completed",
    )
    await db_session.flush()

    row = next(
        row
        for row in await actionable.no_visit_in_months(db_session, test_clinic.id, 12)
        if row.patient_id == patient.id
    )
    assert row.patient_name == "Callable, Test"
    assert row.phone == "+34 600 000 000"
    assert row.days is not None and row.days > 365


@pytest.mark.asyncio
async def test_the_debt_list_is_empty_without_the_payments_contract(
    db_session: AsyncSession, test_clinic: Clinic, monkeypatch
) -> None:
    """App off, empty list — never a failure (ADR 0037)."""
    monkeypatch.setattr(actionable, "provider", lambda _contract: None)
    assert await actionable.owes_and_not_coming_back(db_session, test_clinic.id, Decimal("0")) == []
