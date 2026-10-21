"""The chart's dentition follows the patient's age, unless chosen.

Under 6 deciduous, 6–12 mixed, from 13 permanent (third molars dimmed on the
frontend until 18). A clinician may pick another dentition for a patient; it
is kept per patient and clinic, and `auto` goes back to the age.
"""

from datetime import date
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.odontogram.constants import Dentition, age_in_years, dentition_for_age
from app.modules.patients.models import Patient


def test_age_counts_completed_years() -> None:
    born = date(2018, 6, 15)
    assert age_in_years(born, date(2026, 6, 14)) == 7
    assert age_in_years(born, date(2026, 6, 15)) == 8
    assert age_in_years(None, date(2026, 6, 15)) is None


@pytest.mark.parametrize(
    "age,expected",
    [
        (None, Dentition.PERMANENT),
        (0, Dentition.DECIDUOUS),
        (5, Dentition.DECIDUOUS),
        (6, Dentition.MIXED),
        (12, Dentition.MIXED),
        (13, Dentition.PERMANENT),
        (40, Dentition.PERMANENT),
    ],
)
def test_the_age_suggests_the_dentition(age: int | None, expected: Dentition) -> None:
    assert dentition_for_age(age) is expected


async def _child(db: AsyncSession, clinic: Clinic, born: date | None) -> str:
    patient = Patient(
        id=uuid4(),
        clinic_id=clinic.id,
        first_name="Leo",
        last_name="Ruiz",
        date_of_birth=born,
    )
    db.add(patient)
    await db.commit()
    return str(patient.id)


@pytest.mark.asyncio
async def test_the_chart_says_the_age_and_keeps_the_clinicians_choice(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    today = date.today()
    patient_id = await _child(db_session, test_clinic, date(today.year - 8, 1, 1))
    url = f"/api/v1/odontogram/patients/{patient_id}/odontogram"

    chart = (await client.get(url, headers=auth_headers)).json()["data"]
    assert chart["patient_age"] in (7, 8)
    assert (chart["dentition"], chart["suggested_dentition"]) == ("auto", "mixed")

    chosen = await client.put(
        f"{url}/dentition", json={"dentition": "deciduous"}, headers=auth_headers
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["data"]["dentition"] == "deciduous"
    assert (await client.get(url, headers=auth_headers)).json()["data"]["dentition"] == "deciduous"

    # Back to following the age.
    await client.put(f"{url}/dentition", json={"dentition": "auto"}, headers=auth_headers)
    assert (await client.get(url, headers=auth_headers)).json()["data"]["dentition"] == "auto"

    refused = await client.put(
        f"{url}/dentition", json={"dentition": "adult"}, headers=auth_headers
    )
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_no_birth_date_shows_the_permanent_dentition(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    patient_id = await _child(db_session, test_clinic, None)
    chart = (
        await client.get(
            f"/api/v1/odontogram/patients/{patient_id}/odontogram", headers=auth_headers
        )
    ).json()["data"]
    assert (chart["patient_age"], chart["suggested_dentition"]) == (None, "permanent")


@pytest.mark.asyncio
async def test_another_clinics_patient_cannot_be_given_a_dentition(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    other = Clinic(id=uuid4(), name="Otra", tax_id="B1", settings={}, account_tier="clinic")
    db_session.add(other)
    await db_session.flush()
    patient_id = await _child(db_session, other, date(2020, 1, 1))
    refused = await client.put(
        f"/api/v1/odontogram/patients/{patient_id}/odontogram/dentition",
        json={"dentition": "mixed"},
        headers=auth_headers,
    )
    assert refused.status_code == 404
