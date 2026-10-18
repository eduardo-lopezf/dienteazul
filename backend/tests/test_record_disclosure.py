"""A record does not leave the clinic without saying to whom and why.

ADR 0033. What these pin: the purpose decides the evidence asked for;
scope is enforced, not advisory; the document is stored as it left, with
its digest and a manifest; the disclosure is itself an entry of the
record; and there is one path to a printable record.
"""

import hashlib
import re
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.auth.models import Clinic
from app.core.plugins.registry import module_registry
from app.modules.patients.models import Patient

REFERRAL = {
    "purpose": "continuity_of_care",
    "recipient_name": "Dra. Laura Méndez",
    "evidence": "Valoración de endodoncia en 46",
    "scope": ["patients.identification", "patients_clinical.allergies"],
}


def _url(patient: Patient) -> str:
    return f"/api/v1/record/patients/{patient.id}/disclosures"


async def _allergy(client: AsyncClient, headers: dict, patient: Patient) -> None:
    saved = await client.put(
        f"/api/v1/patients_clinical/patients/{patient.id}/medical-history",
        headers=headers,
        json={"allergies": [{"name": "Penicilina", "severity": "high"}]},
    )
    assert saved.status_code == 200, saved.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_body",
    [
        # A referral with no clinical reason.
        {**REFERRAL, "evidence": ""},
        # A copy for the patient, without checking who is asking.
        {**REFERRAL, "purpose": "patient_copy", "evidence": None},
        # A third party, with nothing said about what the patient signed.
        {**REFERRAL, "purpose": "authorised_third_party", "evidence": None},
        {**REFERRAL, "purpose": "legal_requirement", "evidence": "  "},
    ],
)
async def test_the_purpose_decides_the_evidence_and_nothing_leaves_without_it(
    client: AsyncClient, auth_headers: dict, test_patient: Patient, request_body: dict
) -> None:
    refused = await client.post(_url(test_patient), headers=auth_headers, json=request_body)
    assert refused.status_code == 400, refused.text

    listed = await client.get(_url(test_patient), headers=auth_headers)
    assert listed.json()["data"] == []


@pytest.mark.asyncio
async def test_the_record_is_read_and_handed_over_without_professionals_or_the_catalog(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    """Both are integrated, not required (ADR 0037): the record reads who
    wrote each entry while the directory runs, and does without it."""
    await _allergy(client, auth_headers, test_patient)
    switched_off = [m for m in ("professionals", "catalog") if module_registry.is_installed(m)]
    for module in switched_off:
        module_registry.deactivate(module)
    try:
        record = await client.get(
            f"/api/v1/record/patients/{test_patient.id}", headers=auth_headers
        )
        assert record.status_code == 200, record.text
        assert record.json()["data"]["professionals"] == []

        made = await client.post(_url(test_patient), headers=auth_headers, json=REFERRAL)
        assert made.status_code == 201, made.text
    finally:
        for module in switched_off:
            module_registry.activate(module)


@pytest.mark.asyncio
async def test_a_disclosure_keeps_the_document_as_it_left(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    await _allergy(client, auth_headers, test_patient)

    made = await client.post(_url(test_patient), headers=auth_headers, json=REFERRAL)
    assert made.status_code == 201, made.text
    disclosure = made.json()["data"]
    assert disclosure["scope"] == REFERRAL["scope"]

    document = await client.get(
        f"/api/v1/record/disclosures/{disclosure['id']}/document", headers=auth_headers
    )
    assert document.status_code == 200
    assert document.content.startswith(b"%PDF")
    assert hashlib.sha256(document.content).hexdigest() == disclosure["document_sha256"]

    # The record moves on; what was handed over does not.
    await client.put(
        f"/api/v1/patients_clinical/patients/{test_patient.id}/medical-history",
        headers=auth_headers,
        json={"allergies": []},
    )
    again = await client.get(
        f"/api/v1/record/disclosures/{disclosure['id']}/document", headers=auth_headers
    )
    assert again.content == document.content


@pytest.mark.asyncio
async def test_scope_is_enforced_not_advisory(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    unknown = await client.post(
        _url(test_patient),
        headers=auth_headers,
        json={**REFERRAL, "scope": ["patients.identification", "billing.invoices"]},
    )
    assert unknown.status_code == 400, unknown.text

    # A section with nothing in it is nothing to hand over.
    empty = await client.post(
        _url(test_patient),
        headers=auth_headers,
        json={**REFERRAL, "scope": ["patients_clinical.allergies"]},
    )
    assert empty.status_code == 400, empty.text


@pytest.mark.asyncio
async def test_a_copy_for_the_patient_needs_their_identity_checked(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    made = await client.post(
        _url(test_patient),
        headers=auth_headers,
        json={
            "purpose": "patient_copy",
            "recipient_name": "Test Patient",
            "identity_verified": True,
            "scope": ["patients.identification"],
        },
    )
    assert made.status_code == 201, made.text


@pytest.mark.asyncio
async def test_the_disclosure_is_an_entry_of_the_record_it_disclosed(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    made = await client.post(
        _url(test_patient),
        headers=auth_headers,
        json={**REFERRAL, "scope": ["patients.identification"]},
    )
    disclosure = made.json()["data"]

    record = await client.get(f"/api/v1/record/patients/{test_patient.id}", headers=auth_headers)
    sections = {(s["module"], s["name"]): s for s in record.json()["data"]["sections"]}
    [entry] = sections[("record", "disclosures")]["entries"]
    assert entry["summary"] == "Dra. Laura Méndez"
    assert entry["detail"]["purpose"] == "continuity_of_care"
    assert entry["source_id"] == disclosure["id"]
    # Last in reading order: after everything it could have carried.
    assert record.json()["data"]["sections"][-1]["name"] == "disclosures"


@pytest.mark.asyncio
async def test_a_patient_who_is_not_in_this_clinic_has_no_record_to_hand_over(
    client: AsyncClient, auth_headers: dict, test_clinic: Clinic
) -> None:
    missing = await client.post(
        f"/api/v1/record/patients/{uuid4()}/disclosures", headers=auth_headers, json=REFERRAL
    )
    assert missing.status_code == 404


def test_there_is_one_path_to_a_printable_record() -> None:
    """The chokepoint (ADR 0029): the record is rendered for a disclosure,
    from `disclosure.py`, and from nowhere else."""
    modules = Path(__file__).resolve().parents[1] / "app"
    callers = sorted(
        str(path.relative_to(modules))
        for path in modules.rglob("*.py")
        if re.search(r"\brender_record_pdf\b", path.read_text(encoding="utf-8"))
    )
    assert callers == ["modules/record/disclosure.py", "modules/record/pdf.py"]
