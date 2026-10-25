"""The ASA physical status of a patient.

What these pin: it is a dated, attributed judgement that is appended and
never edited; the newest one not retracted is the current class; a class
of III or more is said where the allergies are said; a mistaken one is
retracted, not deleted, and the one before it stands again; and it
reaches the clinical record.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.patients.models import Patient
from app.modules.patients_clinical import PatientsClinicalModule
from app.modules.patients_clinical.errors import ERROR_CATALOG
from app.modules.patients_clinical.models import AsaAssessment


def _url(patient: Patient) -> str:
    return f"/api/v1/patients_clinical/patients/{patient.id}/asa"


async def _alerts(client: AsyncClient, headers: dict, patient: Patient) -> list[dict]:
    response = await client.get(
        f"/api/v1/patients_clinical/patients/{patient.id}/alerts", headers=headers
    )
    return [a for a in response.json()["data"]["alerts"] if a["type"] == "asa"]


@pytest.mark.asyncio
async def test_a_patient_nobody_assessed_has_no_class(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    status = (await client.get(_url(test_patient), headers=auth_headers)).json()["data"]
    assert status == {"current": None, "history": []}
    assert await _alerts(client, auth_headers, test_patient) == []


@pytest.mark.asyncio
async def test_a_new_assessment_supersedes_the_last_and_keeps_it(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    last_year = (datetime.now(UTC) - timedelta(days=365)).isoformat()
    first = await client.post(
        _url(test_patient), headers=auth_headers, json={"asa_class": 2, "assessed_at": last_year}
    )
    assert first.status_code == 201, first.text
    assert first.json()["data"]["label"] == "II"
    # ASA II is treated in the chair as usual: nothing to warn about.
    assert await _alerts(client, auth_headers, test_patient) == []

    second = await client.post(
        _url(test_patient),
        headers=auth_headers,
        json={"asa_class": 3, "rationale": "Infarto hace 8 meses, estable"},
    )
    assert second.status_code == 201, second.text

    status = (await client.get(_url(test_patient), headers=auth_headers)).json()["data"]
    assert status["current"]["label"] == "III"
    assert [a["label"] for a in status["history"]] == ["III", "II"]
    # The earlier judgement is as it was: nobody rewrote it.
    assert status["history"][1]["id"] == first.json()["data"]["id"]

    [alert] = await _alerts(client, auth_headers, test_patient)
    assert (alert["title"], alert["severity"]) == ("ASA III", "high")
    assert alert["details"] == "Infarto hace 8 meses, estable"


@pytest.mark.asyncio
async def test_class_four_and_the_emergency_modifier(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    made = await client.post(
        _url(test_patient), headers=auth_headers, json={"asa_class": 4, "is_emergency": True}
    )
    assert made.json()["data"]["label"] == "IVE"
    [alert] = await _alerts(client, auth_headers, test_patient)
    assert (alert["title"], alert["severity"]) == ("ASA IVE", "critical")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"asa_class": 0},
        # V and VI exist on the scale and are not offered here.
        {"asa_class": 5},
        {"asa_class": 6},
        {},
    ],
)
async def test_only_classes_one_to_four_are_offered(
    client: AsyncClient, auth_headers: dict, test_patient: Patient, body: dict
) -> None:
    refused = await client.post(_url(test_patient), headers=auth_headers, json=body)
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_a_judgement_is_not_dated_in_the_future(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    refused = await client.post(
        _url(test_patient), headers=auth_headers, json={"asa_class": 1, "assessed_at": tomorrow}
    )
    assert refused.status_code == 400
    definition = ERROR_CATALOG["patients_clinical.asa_assessment.rejected"]
    assert refused.json()["code"] == definition.code
    assert refused.json()["category"] == definition.category.value
    assert refused.json()["reference"] == refused.headers["x-request-id"]


@pytest.mark.asyncio
async def test_a_mistaken_assessment_is_retracted_and_the_previous_one_stands(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_patient: Patient
) -> None:
    await client.post(_url(test_patient), headers=auth_headers, json={"asa_class": 1})
    wrong = await client.post(_url(test_patient), headers=auth_headers, json={"asa_class": 4})
    wrong_id = wrong.json()["data"]["id"]

    taken_back = await client.post(
        f"{_url(test_patient)}/{wrong_id}/retract",
        headers=auth_headers,
        json={"reason": "Paciente equivocado"},
    )
    assert taken_back.status_code == 200, taken_back.text
    assert taken_back.json()["data"]["retracted_at"] is not None

    status = (await client.get(_url(test_patient), headers=auth_headers)).json()["data"]
    assert status["current"]["label"] == "I"
    assert [a["label"] for a in status["history"]] == ["I"]
    assert await _alerts(client, auth_headers, test_patient) == []

    # Still there: what the chart said that day stays answerable.
    rows = (
        (
            await db_session.execute(
                select(AsaAssessment).where(AsaAssessment.patient_id == test_patient.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {r.retraction_reason for r in rows} == {None, "Paciente equivocado"}


@pytest.mark.asyncio
async def test_another_patients_assessment_cannot_be_retracted_through_this_one(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_patient: Patient
) -> None:
    other = Patient(clinic_id=test_patient.clinic_id, first_name="Otra", last_name="Persona")
    db_session.add(other)
    await db_session.commit()
    made = await client.post(_url(other), headers=auth_headers, json={"asa_class": 2})
    assessment_id = made.json()["data"]["id"]

    refused = await client.post(
        f"{_url(test_patient)}/{assessment_id}/retract", headers=auth_headers, json={}
    )
    assert refused.status_code == 404


@pytest.mark.asyncio
async def test_every_assessment_reaches_the_record_on_its_day(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    last_year = (datetime.now(UTC) - timedelta(days=365)).isoformat()
    await client.post(
        _url(test_patient), headers=auth_headers, json={"asa_class": 2, "assessed_at": last_year}
    )
    await client.post(
        _url(test_patient), headers=auth_headers, json={"asa_class": 3, "rationale": "EPOC"}
    )

    record = await client.get(f"/api/v1/record/patients/{test_patient.id}", headers=auth_headers)
    sections = {(s["module"], s["name"]): s for s in record.json()["data"]["sections"]}
    entries = sections[("patients_clinical", "asa_assessments")]["entries"]
    assert sorted(entry["summary"] for entry in entries) == ["ASA II", "ASA III"]
    newest = max(entries, key=lambda entry: entry["occurred_at"])
    assert newest["detail"] == {"asa_class": "ASA III", "rationale": "EPOC"}


def test_assessing_is_its_own_permission_and_a_clinical_one() -> None:
    manifest = PatientsClinicalModule.manifest
    assert "asa.write" in PatientsClinicalModule().get_permissions()
    grants = manifest["role_permissions"]
    assert "asa.write" in grants["dentist"]
    # Nobody who is not a clinician with the patient's history in hand.
    for role in ("hygienist", "assistant", "receptionist"):
        assert "asa.write" not in grants[role]


@pytest.mark.asyncio
async def test_whoever_books_reads_the_class_and_nothing_clinical(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    url = f"{_url(test_patient)}/class"
    nobody = (await client.get(url, headers=auth_headers)).json()["data"]
    assert nobody == {"asa_class": None, "label": None, "is_emergency": False}

    await client.post(
        _url(test_patient),
        headers=auth_headers,
        json={"asa_class": 3, "is_emergency": True, "rationale": "Infarto hace 8 meses"},
    )
    seen = (await client.get(url, headers=auth_headers)).json()["data"]
    assert (seen["asa_class"], seen["label"], seen["is_emergency"]) == (3, "IIIE", True)
    # The class alone. Not when, not why, not who, not what came before.
    assert set(seen) == {"asa_class", "label", "is_emergency"}


def test_reception_reads_the_class_and_not_the_history() -> None:
    grants = PatientsClinicalModule.manifest["role_permissions"]
    for role in ("dentist", "hygienist", "assistant", "receptionist"):
        assert "asa.read" in grants[role], role
    assert "medical.read" not in grants["receptionist"]
    assert "asa.write" not in grants["receptionist"]
