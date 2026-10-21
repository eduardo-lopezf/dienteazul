"""Eruption status per tooth, the primary→permanent exchange, and a clinic's
eruption chronology (phase 2 of the age-aware odontogram)."""

from datetime import date
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.odontogram.constants import DEFAULT_ERUPTION_AGES, successor_of
from app.modules.odontogram.models import OdontogramHistory
from app.modules.patients.models import Patient


def test_each_primary_tooth_knows_its_successor() -> None:
    assert [successor_of(t) for t in (51, 55, 61, 73, 85)] == [11, 15, 21, 33, 45]
    assert successor_of(16) is None


async def _child(db: AsyncSession, clinic: Clinic) -> str:
    patient = Patient(
        id=uuid4(),
        clinic_id=clinic.id,
        first_name="Mía",
        last_name="Soto",
        date_of_birth=date(date.today().year - 9, 1, 1),
    )
    db.add(patient)
    await db.commit()
    return str(patient.id)


@pytest.mark.asyncio
async def test_a_tooth_says_where_it_is_and_the_history_keeps_it(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    patient_id = await _child(db_session, test_clinic)
    url = f"/api/v1/odontogram/patients/{patient_id}/teeth/13"

    said = await client.put(url, json={"eruption_status": "impacted"}, headers=auth_headers)
    assert said.status_code == 200, said.text
    assert said.json()["data"]["eruption_status"] == "impacted"

    # Something else changes on the tooth: the status is not touched.
    other = await client.put(url, json={"notes": "Control"}, headers=auth_headers)
    assert other.json()["data"]["eruption_status"] == "impacted"

    # Null gives the decision back to the chronology.
    cleared = await client.put(url, json={"eruption_status": None}, headers=auth_headers)
    assert cleared.json()["data"]["eruption_status"] is None

    refused = await client.put(url, json={"eruption_status": "lost"}, headers=auth_headers)
    assert refused.status_code == 422

    history = (
        (
            await db_session.execute(
                select(OdontogramHistory).where(
                    OdontogramHistory.patient_id == patient_id,
                    OdontogramHistory.change_type == "eruption",
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(h.old_condition, h.new_condition) for h in history] == [
        (None, "impacted"),
        ("impacted", None),
    ]


@pytest.mark.asyncio
async def test_an_exchange_marks_the_primary_fallen_and_the_successor_coming(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    patient_id = await _child(db_session, test_clinic)
    url = f"/api/v1/odontogram/patients/{patient_id}/odontogram/exchange"

    done = await client.post(url, json={"primary_tooth": 54}, headers=auth_headers)
    assert done.status_code == 200, done.text
    data = done.json()["data"]
    assert (data["primary"]["tooth_number"], data["primary"]["eruption_status"]) == (
        54,
        "exfoliated",
    )
    assert (data["successor"]["tooth_number"], data["successor"]["eruption_status"]) == (
        14,
        "erupting",
    )

    # A successor already said to be in the mouth stays so.
    await client.put(
        f"/api/v1/odontogram/patients/{patient_id}/teeth/11",
        json={"eruption_status": "erupted"},
        headers=auth_headers,
    )
    again = await client.post(url, json={"primary_tooth": 51}, headers=auth_headers)
    assert again.json()["data"]["successor"]["eruption_status"] == "erupted"

    refused = await client.post(url, json={"primary_tooth": 16}, headers=auth_headers)
    assert refused.status_code == 400


@pytest.mark.asyncio
async def test_a_clinic_keeps_its_own_eruption_chronology(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    url = "/api/v1/odontogram/settings/eruption-ages"
    assert (await client.get(url, headers=auth_headers)).json()["data"] == DEFAULT_ERUPTION_AGES

    # Only what differs need be sent.
    own = await client.put(url, json={"ages": {"upper": {"7": 11}}}, headers=auth_headers)
    assert own.status_code == 200, own.text
    assert own.json()["data"]["upper"]["7"] == 11
    assert own.json()["data"]["lower"] == DEFAULT_ERUPTION_AGES["lower"]

    patient_id = await _child(db_session, test_clinic)
    chart = (
        await client.get(
            f"/api/v1/odontogram/patients/{patient_id}/odontogram", headers=auth_headers
        )
    ).json()["data"]
    assert chart["eruption_ages"]["upper"]["7"] == 11
    assert chart["eruption_tolerance"] == 2

    for bad in ({"middle": {"1": 7}}, {"upper": {"9": 7}}, {"upper": {"1": 40}}):
        refused = await client.put(url, json={"ages": bad}, headers=auth_headers)
        assert refused.status_code == 422, bad

    reset = await client.put(url, json={"ages": None}, headers=auth_headers)
    assert reset.json()["data"] == DEFAULT_ERUPTION_AGES


@pytest.mark.asyncio
async def test_another_clinics_patient_has_no_teeth_to_exchange(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    other = Clinic(id=uuid4(), name="Otra", tax_id="B2", settings={}, account_tier="clinic")
    db_session.add(other)
    await db_session.flush()
    patient_id = await _child(db_session, other)
    refused = await client.post(
        f"/api/v1/odontogram/patients/{patient_id}/odontogram/exchange",
        json={"primary_tooth": 54},
        headers=auth_headers,
    )
    assert refused.status_code == 404
