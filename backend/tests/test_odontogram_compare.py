"""A past date of the chart, as it stood then — what comparing two dates
side by side rests on."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.odontogram.models import OdontogramHistory, Treatment
from app.modules.patients.models import Patient

TODAY = datetime.now(UTC).date()


def _days_ago(days: int) -> datetime:
    return datetime.combine(TODAY - timedelta(days=days), datetime.min.time(), tzinfo=UTC)


async def _child(db: AsyncSession, clinic: Clinic) -> str:
    patient = Patient(
        id=uuid4(),
        clinic_id=clinic.id,
        first_name="Iker",
        last_name="Ruiz",
        # Nine on 1 January: mixed dentition now, eight a year ago.
        date_of_birth=date(TODAY.year - 9, 1, 1),
    )
    db.add(patient)
    await db.commit()
    return str(patient.id)


async def _at(client: AsyncClient, headers: dict, patient_id: str, day: date) -> dict:
    response = await client.get(
        f"/api/v1/odontogram/patients/{patient_id}/odontogram/at",
        params={"date": day.isoformat()},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_work_done_later_was_still_planned_on_an_earlier_date(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    patient_id = await _child(db_session, test_clinic)
    created = await client.post(
        f"/api/v1/odontogram/patients/{patient_id}/treatments",
        headers=auth_headers,
        json={
            "clinical_type": "filling_composite",
            "tooth_numbers": [16],
            "surfaces": ["O"],
            "status": "planned",
            "scope": "tooth",
        },
    )
    assert created.status_code == 201, created.text
    treatment_id = UUID(created.json()["data"]["id"])
    # Planned ten days ago, done two days ago.
    await db_session.execute(
        update(Treatment)
        .where(Treatment.id == treatment_id)
        .values(recorded_at=_days_ago(10), status="performed", performed_at=_days_ago(2))
    )
    await db_session.commit()

    before = await _at(client, auth_headers, patient_id, TODAY - timedelta(days=5))
    [then] = before["treatments"]
    assert (then["status"], then["performed_at"]) == ("planned", None)

    after = await _at(client, auth_headers, patient_id, TODAY)
    assert after["treatments"][0]["status"] == "performed"

    # Before it was planned, it was not there at all.
    assert (await _at(client, auth_headers, patient_id, TODAY - timedelta(days=20)))[
        "treatments"
    ] == []


@pytest.mark.asyncio
async def test_a_past_date_knows_where_each_tooth_stood_and_how_old_the_patient_was(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    patient_id = await _child(db_session, test_clinic)
    exchange = await client.post(
        f"/api/v1/odontogram/patients/{patient_id}/odontogram/exchange",
        json={"primary_tooth": 54},
        headers=auth_headers,
    )
    assert exchange.status_code == 200, exchange.text
    # The exchange was charted thirty days ago.
    rows = (
        (
            await db_session.execute(
                select(OdontogramHistory).where(
                    OdontogramHistory.patient_id == UUID(patient_id),
                    OdontogramHistory.change_type == "eruption",
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.changed_at = _days_ago(30)
    await db_session.commit()

    then = await _at(client, auth_headers, patient_id, TODAY - timedelta(days=10))
    statuses = {t["tooth_number"]: t["eruption_status"] for t in then["teeth"]}
    assert statuses == {54: "exfoliated", 14: "erupting"}

    earlier = await _at(client, auth_headers, patient_id, TODAY - timedelta(days=60))
    assert earlier["teeth"] == []

    a_year_ago = TODAY - timedelta(days=366)
    past = await _at(client, auth_headers, patient_id, a_year_ago)
    now = await _at(client, auth_headers, patient_id, TODAY)
    assert past["date"] == a_year_ago.isoformat()
    assert past["patient_age"] == now["patient_age"] - 1
    assert now["suggested_dentition"] == "mixed"
