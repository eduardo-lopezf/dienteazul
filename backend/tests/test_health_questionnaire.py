"""The health questionnaire a patient answers at a visit.

What these pin: it is a dated declaration, kept as given; only what the
form asks can be answered; a sheet filled in by hand is filed as a scan of
this same patient; a mistaken one is retracted, never deleted; and it
reaches the clinical record.
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, User
from app.modules.media.models import Document
from app.modules.patients.models import Patient
from app.modules.patients_clinical.questionnaire import CONDITION_GROUPS, CONDITIONS, QUESTIONS

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=="

ANSWERED = {
    # On screen the patient signs what they declared.
    "signature": {"png": PNG, "signed_by_name": "Ana Ruiz"},
    "chief_complaint": "Dolor en molar inferior derecho",
    "blood_type": "O+",
    "answers": {
        "taking_medication": {"answer": True, "detail": "Losartán 50 mg"},
        "major_bleeding": {"answer": False},
    },
    # Out of the form's order on purpose.
    "conditions": ["diabetes", "hypertension"],
}


def _url(patient: Patient) -> str:
    return f"/api/v1/patients_clinical/patients/{patient.id}/questionnaires"


def test_the_form_asks_what_the_paper_form_asks() -> None:
    assert len(QUESTIONS) == 12 and len(CONDITIONS) == 67
    # No condition is listed twice across the blocks.
    assert sum(len(group) for group in CONDITION_GROUPS.values()) == len(CONDITIONS)


@pytest.mark.asyncio
async def test_what_the_patient_declared_is_kept_and_reaches_the_record(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    made = await client.post(_url(test_patient), headers=auth_headers, json=ANSWERED)
    assert made.status_code == 201, made.text
    saved = made.json()["data"]
    assert saved["conditions"] == ["hypertension", "diabetes"]  # the form's order
    assert saved["answers"]["taking_medication"]["detail"] == "Losartán 50 mg"

    record = await client.get(f"/api/v1/record/patients/{test_patient.id}", headers=auth_headers)
    data = record.json()["data"]
    sections = {(s["module"], s["name"]): s for s in data["sections"]}
    [entry] = sections[("patients_clinical", "health_questionnaires")]["entries"]
    assert entry["summary"] == "Dolor en molar inferior derecho"
    # Only what was answered "yes" is what a reader scans for.
    assert entry["detail"]["affirmative_answers"] == [
        {"question": "taking_medication", "detail": "Losartán 50 mg"}
    ]
    coverage = {item["key"]: item["met"] for item in data["coverage"]}
    assert coverage["chief_complaint"] and coverage["personal_history"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"answers": {"favourite_colour": {"answer": True}}},
        {"conditions": ["lycanthropy"]},
        {},
    ],
)
async def test_only_what_the_form_asks_can_be_answered(
    client: AsyncClient, auth_headers: dict, test_patient: Patient, body: dict
) -> None:
    refused = await client.post(_url(test_patient), headers=auth_headers, json=body)
    assert refused.status_code == 400, refused.text


@pytest.mark.asyncio
async def test_a_sheet_filled_in_by_hand_is_filed_as_a_scan_of_the_same_patient(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    other = Patient(id=uuid4(), clinic_id=test_clinic.id, first_name="Otra", last_name="Persona")
    db_session.add(other)
    uploader = (await db_session.execute(select(User))).scalars().first()

    def scan(patient: Patient) -> Document:
        return Document(
            clinic_id=test_clinic.id,
            patient_id=patient.id,
            document_type="report",
            title="Cuestionario",
            original_filename="cuestionario.pdf",
            storage_path=f"test/{uuid4()}.pdf",
            mime_type="application/pdf",
            file_size=1,
            uploaded_by=uploader.id,
        )

    mine, theirs = scan(test_patient), scan(other)
    db_session.add_all([mine, theirs])
    await db_session.commit()

    refused = await client.post(
        _url(test_patient), headers=auth_headers, json={"scan_document_id": str(theirs.id)}
    )
    assert refused.status_code == 400, refused.text

    filed = await client.post(
        _url(test_patient),
        headers=auth_headers,
        json={"chief_complaint": "Revisión", "scan_document_id": str(mine.id)},
    )
    assert filed.status_code == 201, filed.text
    assert filed.json()["data"]["scan_document_id"] == str(mine.id)


@pytest.mark.asyncio
async def test_a_mistaken_questionnaire_is_retracted_not_deleted(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    made = (await client.post(_url(test_patient), headers=auth_headers, json=ANSWERED)).json()
    retracted = await client.post(
        f"{_url(test_patient)}/{made['data']['id']}/retract",
        headers=auth_headers,
        json={"reason": "Paciente equivocado"},
    )
    assert retracted.status_code == 200, retracted.text

    listed = await client.get(_url(test_patient), headers=auth_headers)
    assert listed.json()["data"] == []
    full = await client.get(
        f"/api/v1/record/patients/{test_patient.id}?include_retracted=true", headers=auth_headers
    )
    sections = {(s["module"], s["name"]): s for s in full.json()["data"]["sections"]}
    [entry] = sections[("patients_clinical", "health_questionnaires")]["entries"]
    assert entry["status"] == "retracted"


@pytest.mark.asyncio
async def test_the_blank_form_prints(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    for locale in ("es", "en"):
        form = await client.get(
            f"/api/v1/patients_clinical/patients/{test_patient.id}/questionnaire-form?locale={locale}",
            headers=auth_headers,
        )
        assert form.status_code == 200, form.text
        assert form.headers["content-type"] == "application/pdf"
        assert form.content.startswith(b"%PDF")


# --- The patient's signature, on screen ------------------------------------


@pytest.mark.asyncio
async def test_a_questionnaire_signed_on_screen_keeps_who_signed_and_under_what(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    test_clinic.address = {"country": "MX"}
    await db_session.commit()

    made = await client.post(
        _url(test_patient),
        headers=auth_headers,
        json={
            **ANSWERED,
            "signature": {
                "png": PNG,
                "signed_by_name": " Ana Ruiz ",
                "signer_capacity": "guardian",
            },
        },
    )
    assert made.status_code == 201, made.text
    saved = made.json()["data"]
    assert saved["signed_by_name"] == "Ana Ruiz" and saved["signer_capacity"] == "guardian"
    assert saved["signed_at"] is not None
    assert saved["signature_data"] == {"png": PNG}
    assert saved["regulation"] == "NOM-004-SSA3-2012, Del expediente clínico"

    # The clinic changes its line afterwards: what was signed under stays.
    await client.put(
        "/api/v1/auth/clinic/settings/record-regulation",
        headers=auth_headers,
        json={"text": "Otra norma"},
    )
    listed = (await client.get(_url(test_patient), headers=auth_headers)).json()["data"]
    assert listed[0]["regulation"] == "NOM-004-SSA3-2012, Del expediente clínico"

    record = await client.get(f"/api/v1/record/patients/{test_patient.id}", headers=auth_headers)
    sections = {(s["module"], s["name"]): s for s in record.json()["data"]["sections"]}
    [entry] = sections[("patients_clinical", "health_questionnaires")]["entries"]
    assert entry["detail"]["signed_by_name"] == "Ana Ruiz"
    assert entry["detail"]["signer_capacity"] == "guardian"
    # The drawing itself is not part of what the record composes.
    assert "signature_data" not in entry["detail"]


@pytest.mark.asyncio
async def test_a_questionnaire_answered_on_screen_is_not_kept_unsigned(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    unsigned = {key: value for key, value in ANSWERED.items() if key != "signature"}
    refused = await client.post(_url(test_patient), headers=auth_headers, json=unsigned)
    assert refused.status_code == 400
    assert "signed" in refused.json()["message"]
    # Nothing was kept.
    assert (await client.get(_url(test_patient), headers=auth_headers)).json()["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "signature",
    [
        # Not a drawing.
        {"png": "javascript:alert(1)", "signed_by_name": "Ana"},
        # Nobody's.
        {"png": PNG, "signed_by_name": ""},
        # Signed as something that does not exist.
        {"png": PNG, "signed_by_name": "Ana", "signer_capacity": "neighbour"},
    ],
)
async def test_a_signature_is_a_drawing_with_a_name_and_a_capacity(
    client: AsyncClient, auth_headers: dict, test_patient: Patient, signature: dict
) -> None:
    refused = await client.post(
        _url(test_patient), headers=auth_headers, json={**ANSWERED, "signature": signature}
    )
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_a_sheet_filled_in_by_hand_is_not_signed_on_screen_too(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_patient: Patient,
) -> None:
    uploader = (await db_session.execute(select(User.id).limit(1))).scalar_one()
    scan = Document(
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        document_type="report",
        title="Cuestionario",
        original_filename="c.pdf",
        storage_path=f"sign-test/{uuid4()}.pdf",
        mime_type="application/pdf",
        file_size=10,
        uploaded_by=uploader,
    )
    db_session.add(scan)
    await db_session.commit()

    refused = await client.post(
        _url(test_patient),
        headers=auth_headers,
        json={
            "scan_document_id": str(scan.id),
            "signature": {"png": PNG, "signed_by_name": "Ana"},
        },
    )
    assert refused.status_code == 400
