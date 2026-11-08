"""The receiver's fiscal profile, kept once per RFC.

The SAT needs the receiver's tax regime, fiscal postal code and CFDI use.
They belong to the taxpayer, so they are kept by RFC: a relative who pays
with their own RFC is asked once, whatever patient the invoice is for.
The general public (``XAXX010101000``) needs none: ``616``, ``S01`` and
the postal code of issue.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, User
from app.modules.billing.models import Invoice, InvoiceItem, InvoiceSeries
from app.modules.patients.models import Patient

from .conftest import configure_issuer

RFC = "GOMA800101AB1"


async def _put(client: AsyncClient, headers: dict, rfc: str = RFC, **body):
    return await client.put(
        f"/api/v1/sat_cfdi/receivers/{rfc}",
        json={"tax_regime": "612", "tax_zip_code": "06600", "cfdi_use": "D01", **body},
        headers=headers,
    )


@pytest.mark.asyncio
async def test_a_profile_is_kept_by_rfc(
    client: AsyncClient, auth_headers: dict, mexican_clinic: Clinic
) -> None:
    missing = await client.get(f"/api/v1/sat_cfdi/receivers/{RFC}", headers=auth_headers)
    assert missing.status_code == 200, missing.text
    assert missing.json()["data"] is None

    saved = await _put(client, auth_headers, "goma800101ab1")
    assert saved.status_code == 200, saved.text

    data = (await client.get(f"/api/v1/sat_cfdi/receivers/{RFC}", headers=auth_headers)).json()
    assert {k: data["data"][k] for k in ("rfc", "tax_regime", "tax_zip_code", "cfdi_use")} == {
        "rfc": RFC,
        "tax_regime": "612",
        "tax_zip_code": "06600",
        "cfdi_use": "D01",
    }

    changed = await _put(client, auth_headers, cfdi_use="G03")
    assert changed.json()["data"]["cfdi_use"] == "G03"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rfc", "body"),
    [
        ("NOESRFC", {}),
        (RFC, {"tax_regime": "999"}),
        (RFC, {"tax_zip_code": "660"}),
        (RFC, {"cfdi_use": "ZZ9"}),
    ],
)
async def test_a_profile_must_be_the_sat_s(
    client: AsyncClient, auth_headers: dict, mexican_clinic: Clinic, rfc: str, body: dict
) -> None:
    response = await _put(client, auth_headers, rfc, **body)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_an_invoice_to_an_rfc_needs_its_profile(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexican_clinic: Clinic,
    test_patient: Patient,
) -> None:
    db_session.add(
        InvoiceSeries(
            id=uuid4(),
            clinic_id=mexican_clinic.id,
            prefix="FAC",
            series_type="invoice",
            is_default=True,
        )
    )
    invoice = Invoice(
        id=uuid4(),
        clinic_id=mexican_clinic.id,
        patient_id=test_patient.id,
        status="draft",
        billing_name="ANA GOMEZ MARTINEZ",
        billing_tax_id=RFC,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        created_by=(await db_session.execute(select(User))).scalars().first().id,
    )
    db_session.add(invoice)
    await db_session.flush()
    db_session.add(
        InvoiceItem(
            id=uuid4(),
            clinic_id=mexican_clinic.id,
            invoice_id=invoice.id,
            description="Limpieza dental",
            unit_price=Decimal("100.00"),
            quantity=1,
            vat_rate=0.0,
            line_subtotal=Decimal("100.00"),
            line_tax=Decimal("0.00"),
            line_total=Decimal("100.00"),
            display_order=0,
        )
    )
    await db_session.commit()
    await configure_issuer(client, auth_headers)

    refused = await client.post(
        f"/api/v1/billing/invoices/{invoice.id}/issue", json={}, headers=auth_headers
    )
    assert refused.status_code == 400, refused.text
    assert "régimen" in refused.text

    await _put(client, auth_headers)
    issued = await client.post(
        f"/api/v1/billing/invoices/{invoice.id}/issue", json={}, headers=auth_headers
    )
    assert issued.status_code == 200, issued.text


@pytest.mark.asyncio
async def test_a_patient_s_export_carries_the_profiles_of_their_invoices(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexican_clinic: Clinic,
    test_patient: Patient,
) -> None:
    from app.modules.sat_cfdi.privacy import get_subject_contributors

    await _put(client, auth_headers)
    await _put(client, auth_headers, "XYZA800101AB1")
    db_session.add(
        Invoice(
            id=uuid4(),
            clinic_id=mexican_clinic.id,
            patient_id=test_patient.id,
            status="draft",
            billing_name="ANA GOMEZ MARTINEZ",
            billing_tax_id=" goma800101ab1",
            subtotal=Decimal("0"),
            total=Decimal("0"),
            created_by=(await db_session.execute(select(User))).scalars().first().id,
        )
    )
    await db_session.commit()

    [receivers] = [c for c in get_subject_contributors() if c.name == "sat_receivers"]
    exported = await receivers.export(db_session, mexican_clinic.id, test_patient.id)

    assert [row["rfc"] for row in exported] == [RFC]
