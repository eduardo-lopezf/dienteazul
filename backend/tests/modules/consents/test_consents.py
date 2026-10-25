"""Consent letters: informed consent (Art. 51 Bis 1, NOM-004) and data use.

What these pin: a letter is written from a template and keeps its own copy
of the text; an informed consent names who explained it; once signed it is
a record — not edited, not deleted, only revoked; and it shows up in the
patient's clinical record.
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, User
from app.core.plugins.registry import module_registry
from app.modules.consents.errors import ERROR_CATALOG
from app.modules.media.models import Document
from app.modules.patients.models import Patient
from app.modules.professionals.models import Professional

BASE = "/api/v1/consents"
RISKS = "Riesgos: dolor, inflamación, alveolitis. Alternativas: conservar la pieza."


@pytest.fixture
async def dentist(db_session: AsyncSession, test_clinic: Clinic) -> Professional:
    professional = Professional(
        id=uuid4(),
        clinic_id=test_clinic.id,
        first_name="Marta",
        last_name="Ruiz",
        professional_type="dentist",
        license_number="CED-12345",
        is_active=True,
    )
    db_session.add(professional)
    await db_session.commit()
    return professional


async def _template(client: AsyncClient, headers: dict, kind: str = "informed") -> dict:
    created = await client.post(
        f"{BASE}/templates",
        headers=headers,
        json={"kind": kind, "title": "Extracción dental", "body": RISKS},
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]


async def _draft(client: AsyncClient, headers: dict, patient: Patient, **extra) -> dict:
    template = await _template(client, headers)
    created = await client.post(
        f"{BASE}/patients/{patient.id}",
        headers=headers,
        json={"kind": "informed", "template_id": template["id"], **extra},
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]


SIGNATURE = {"signed_by_name": "Test Patient", "signer_capacity": "patient"}


@pytest.mark.asyncio
async def test_a_consent_is_written_from_a_template_and_keeps_its_own_text(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    template = await _template(client, auth_headers)
    created = await client.post(
        f"{BASE}/patients/{test_patient.id}",
        headers=auth_headers,
        json={"kind": "informed", "template_id": template["id"], "procedure_label": "Pieza 48"},
    )
    consent = created.json()["data"]
    assert consent["status"] == "draft"
    assert consent["body"] == RISKS and consent["template_version"] == 1

    # Rewording the template is a new version, and does not reach the letter.
    edited = await client.put(
        f"{BASE}/templates/{template['id']}", headers=auth_headers, json={"body": "Otro texto"}
    )
    assert edited.json()["data"]["version"] == 2
    again = await client.get(f"{BASE}/{consent['id']}", headers=auth_headers)
    assert again.json()["data"]["body"] == RISKS


@pytest.mark.asyncio
async def test_an_informed_consent_cannot_be_signed_without_who_explained_it(
    client: AsyncClient, auth_headers: dict, test_patient: Patient, dentist: Professional
) -> None:
    consent = await _draft(client, auth_headers, test_patient)

    refused = await client.post(
        f"{BASE}/{consent['id']}/sign", headers=auth_headers, json=SIGNATURE
    )
    assert refused.status_code == 400, refused.text

    named = await client.put(
        f"{BASE}/{consent['id']}",
        headers=auth_headers,
        json={"explained_by_professional_id": str(dentist.id)},
    )
    assert named.json()["data"]["explained_by_name"] == "Marta Ruiz"
    assert named.json()["data"]["explained_by_license"] == "CED-12345"

    signed = await client.post(
        f"{BASE}/{consent['id']}/sign",
        headers=auth_headers,
        json={**SIGNATURE, "signature_data": {"png": "data:image/png;base64,AAAA"}},
    )
    assert signed.status_code == 200, signed.text
    data = signed.json()["data"]
    assert data["status"] == "signed" and data["signed_at"] is not None
    assert data["signed_by_name"] == "Test Patient"


@pytest.mark.asyncio
async def test_a_signed_consent_is_a_record_it_is_revoked_never_edited(
    client: AsyncClient, auth_headers: dict, test_patient: Patient, dentist: Professional
) -> None:
    consent = await _draft(
        client, auth_headers, test_patient, explained_by_professional_id=str(dentist.id)
    )
    url = f"{BASE}/{consent['id']}"
    await client.post(f"{url}/sign", headers=auth_headers, json=SIGNATURE)

    refused = await client.put(url, headers=auth_headers, json={"body": "cambiado"})
    assert refused.status_code == 409
    definition = ERROR_CATALOG["consents.consent.invalid_state"]
    assert refused.json()["code"] == definition.code
    assert refused.json()["category"] == definition.category.value
    assert refused.json()["reference"] == refused.headers["x-request-id"]
    assert (await client.post(f"{url}/discard", headers=auth_headers)).status_code == 409
    assert (
        await client.post(f"{url}/sign", headers=auth_headers, json=SIGNATURE)
    ).status_code == 409

    revoked = await client.post(
        f"{url}/revoke", headers=auth_headers, json={"note": "El paciente cambió de opinión"}
    )
    data = revoked.json()["data"]
    assert data["status"] == "revoked" and data["revoked_at"] is not None
    # What was signed is still there.
    assert data["signed_by_name"] == "Test Patient" and data["body"] == RISKS


@pytest.mark.asyncio
async def test_a_declined_consent_is_kept_and_a_discarded_draft_is_not_listed(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    declined = await _draft(client, auth_headers, test_patient)
    discarded = await _draft(client, auth_headers, test_patient)
    await client.post(
        f"{BASE}/{declined['id']}/decline", headers=auth_headers, json={"note": "No acepta"}
    )
    await client.post(f"{BASE}/{discarded['id']}/discard", headers=auth_headers)

    listed = await client.get(f"{BASE}/patients/{test_patient.id}", headers=auth_headers)
    statuses = {c["id"]: c["status"] for c in listed.json()["data"]}
    assert statuses == {declined["id"]: "declined"}


@pytest.mark.asyncio
async def test_a_data_use_consent_needs_no_professional(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    template = await _template(client, auth_headers, kind="data_use")
    created = await client.post(
        f"{BASE}/patients/{test_patient.id}",
        headers=auth_headers,
        json={"kind": "data_use", "template_id": template["id"]},
    )
    signed = await client.post(
        f"{BASE}/{created.json()['data']['id']}/sign", headers=auth_headers, json=SIGNATURE
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["data"]["template_version"] == 1


@pytest.mark.asyncio
async def test_a_template_of_another_kind_is_refused(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    template = await _template(client, auth_headers, kind="data_use")
    refused = await client.post(
        f"{BASE}/patients/{test_patient.id}",
        headers=auth_headers,
        json={"kind": "informed", "template_id": template["id"]},
    )
    assert refused.status_code == 400


@pytest.mark.asyncio
async def test_consents_work_while_the_professionals_app_is_off(
    client: AsyncClient, auth_headers: dict, test_patient: Patient, dentist: Professional
) -> None:
    """The directory is an integration (ADR 0037): drafts are written and a
    data-use consent is signed; naming a professional is refused."""
    module_registry.deactivate("professionals")
    try:
        draft = await _draft(client, auth_headers, test_patient)
        named = await client.put(
            f"{BASE}/{draft['id']}",
            headers=auth_headers,
            json={"explained_by_professional_id": str(dentist.id)},
        )
    finally:
        module_registry.activate("professionals")

    assert draft["status"] == "draft"
    assert named.status_code == 400 and "not available" in named.text


@pytest.mark.asyncio
async def test_a_signed_consent_is_part_of_the_clinical_record(
    client: AsyncClient, auth_headers: dict, test_patient: Patient, dentist: Professional
) -> None:
    signed = await _draft(
        client, auth_headers, test_patient, explained_by_professional_id=str(dentist.id)
    )
    await client.post(f"{BASE}/{signed['id']}/sign", headers=auth_headers, json=SIGNATURE)
    await _draft(client, auth_headers, test_patient)  # a draft, which is not a record

    record = await client.get(f"/api/v1/record/patients/{test_patient.id}", headers=auth_headers)
    assert record.status_code == 200, record.text
    sections = {(s["module"], s["name"]): s for s in record.json()["data"]["sections"]}
    entries = sections[("consents", "consents")]["entries"]
    assert [e["summary"] for e in entries] == ["Extracción dental"]
    assert entries[0]["detail"]["status"] == "signed"


@pytest.mark.asyncio
async def test_another_clinics_consent_is_not_found(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_patient: Patient
) -> None:
    from app.modules.consents.models import Consent

    other = Clinic(
        id=uuid4(),
        name="Otra",
        tax_id="B00000001",
        address={"street": "x", "city": "y"},
        settings={},
        account_tier="clinic",
    )
    db_session.add(other)
    await db_session.flush()
    foreign_patient = Patient(id=uuid4(), clinic_id=other.id, first_name="A", last_name="B")
    db_session.add(foreign_patient)
    await db_session.flush()
    foreign = Consent(
        id=uuid4(),
        clinic_id=other.id,
        patient_id=foreign_patient.id,
        kind="data_use",
        title="t",
        body="b",
    )
    db_session.add(foreign)
    await db_session.commit()

    missing = await client.get(f"{BASE}/{foreign.id}", headers=auth_headers)
    assert missing.status_code == 404
    definition = ERROR_CATALOG["consents.consent.not_found"]
    assert missing.json()["code"] == definition.code
    assert missing.json()["category"] == definition.category.value
    assert missing.json()["reference"] == missing.headers["x-request-id"]
    refused = await client.post(
        f"{BASE}/patients/{foreign_patient.id}",
        headers=auth_headers,
        json={"kind": "data_use", "title": "t", "body": "b"},
    )
    assert refused.status_code == 400


# --- Signed on paper ---------------------------------------------------------


async def _scan(db_session: AsyncSession, patient: Patient) -> Document:
    """The scanned letter, as the Media module files it for a patient."""
    uploader = (await db_session.execute(select(User))).scalars().first()
    document = Document(
        clinic_id=patient.clinic_id,
        patient_id=patient.id,
        document_type="consent",
        title="Carta firmada",
        original_filename="carta.pdf",
        storage_path=f"test/{uuid4()}.pdf",
        mime_type="application/pdf",
        file_size=1024,
        uploaded_by=uploader.id,
    )
    db_session.add(document)
    await db_session.commit()
    return document


@pytest.mark.asyncio
async def test_a_consent_signed_on_paper_is_filed_with_its_scan(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_patient: Patient,
    dentist: Professional,
) -> None:
    consent = await _draft(
        client, auth_headers, test_patient, explained_by_professional_id=str(dentist.id)
    )
    url = f"{BASE}/{consent['id']}/sign"

    # On paper the scan is the signature: without it there is nothing to file.
    bare = await client.post(url, headers=auth_headers, json={**SIGNATURE, "method": "paper"})
    assert bare.status_code == 422, bare.text

    scan = await _scan(db_session, test_patient)
    signed = await client.post(
        url,
        headers=auth_headers,
        json={**SIGNATURE, "method": "paper", "document_id": str(scan.id)},
    )
    assert signed.status_code == 200, signed.text
    data = signed.json()["data"]
    assert data["status"] == "signed" and data["signature_method"] == "paper"
    assert data["signature_data"] == {"document_id": str(scan.id)}

    record = await client.get(f"/api/v1/record/patients/{test_patient.id}", headers=auth_headers)
    sections = {(s["module"], s["name"]): s for s in record.json()["data"]["sections"]}
    [entry] = sections[("consents", "consents")]["entries"]
    assert entry["detail"]["scan_document_id"] == str(scan.id)


@pytest.mark.asyncio
async def test_the_scan_must_be_a_document_of_the_same_patient(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
    dentist: Professional,
) -> None:
    other = Patient(id=uuid4(), clinic_id=test_clinic.id, first_name="Otra", last_name="Persona")
    db_session.add(other)
    await db_session.commit()
    scan = await _scan(db_session, other)
    consent = await _draft(
        client, auth_headers, test_patient, explained_by_professional_id=str(dentist.id)
    )

    refused = await client.post(
        f"{BASE}/{consent['id']}/sign",
        headers=auth_headers,
        json={**SIGNATURE, "method": "paper", "document_id": str(scan.id)},
    )
    assert refused.status_code == 400, refused.text
    again = await client.get(f"{BASE}/{consent['id']}", headers=auth_headers)
    assert again.json()["data"]["status"] == "draft"


@pytest.mark.asyncio
async def test_a_consent_prints_as_a_sheet(
    client: AsyncClient, auth_headers: dict, test_patient: Patient, dentist: Professional
) -> None:
    """A draft is a form to sign by hand; a letter signed on screen prints too."""
    consent = await _draft(
        client, auth_headers, test_patient, explained_by_professional_id=str(dentist.id)
    )
    url = f"{BASE}/{consent['id']}"

    blank = await client.get(f"{url}/pdf", headers=auth_headers)
    assert blank.status_code == 200, blank.text
    assert blank.headers["content-type"] == "application/pdf"
    assert blank.content.startswith(b"%PDF")

    await client.post(
        f"{url}/sign",
        headers=auth_headers,
        json={**SIGNATURE, "signature_data": {"png": "data:image/png;base64,AAAA"}},
    )
    signed = await client.get(f"{url}/pdf?locale=en", headers=auth_headers)
    assert signed.status_code == 200 and signed.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_agreement_with_a_concluded_treatment_is_a_letter_of_its_own(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    """The *firma de conformidad* of a paper chart: no professional to name,
    and it stands for neither of the two consents."""
    created = await client.post(
        f"{BASE}/patients/{test_patient.id}",
        headers=auth_headers,
        json={
            "kind": "conformity",
            "title": "Conformidad",
            "body": "El tratamiento se concluyó a mi satisfacción.",
            "procedure_label": "Endodoncia 46",
        },
    )
    assert created.status_code == 201, created.text
    url = f"{BASE}/{created.json()['data']['id']}"

    signed = await client.post(f"{url}/sign", headers=auth_headers, json=SIGNATURE)
    assert signed.status_code == 200, signed.text
    assert signed.json()["data"]["kind"] == "conformity"
    assert (await client.get(f"{url}/pdf", headers=auth_headers)).content.startswith(b"%PDF")

    record = await client.get(f"/api/v1/record/patients/{test_patient.id}", headers=auth_headers)
    coverage = {item["key"]: item["met"] for item in record.json()["data"]["coverage"]}
    assert coverage["informed_consent"] is False
