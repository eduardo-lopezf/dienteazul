"""The SAT module's skeleton: what its hook writes and refuses (ADR 0067).

Nothing here reaches Facturama — the hook never calls out. It validates
the receiver's RFC before an issue, queues a ``pending`` CFDI for every
invoice and credit note, and turns a cancellation into a request that
waits for the SAT.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, User
from app.modules.billing.hooks import BillingHookRegistry
from app.modules.billing.models import Invoice, InvoiceItem, InvoiceSeries
from app.modules.patients.models import Patient
from app.modules.sat_cfdi.hook import SatCfdiHook
from app.modules.sat_cfdi.models import SatCfdi

from .conftest import configure_issuer

PUBLIC = "XAXX010101000"


@pytest_asyncio.fixture
async def mexico(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, mexican_clinic: Clinic
) -> Clinic:
    """A Mexican clinic with series, SAT settings and a CSD: ready to issue."""
    for series_type, prefix in (("invoice", "FAC"), ("credit_note", "NC")):
        db_session.add(
            InvoiceSeries(
                id=uuid4(),
                clinic_id=mexican_clinic.id,
                prefix=prefix,
                series_type=series_type,
                is_default=True,
            )
        )
    await db_session.commit()
    await configure_issuer(client, auth_headers)
    return mexican_clinic


async def _draft(db: AsyncSession, clinic: Clinic, patient: Patient, tax_id: str) -> Invoice:
    invoice = Invoice(
        id=uuid4(),
        clinic_id=clinic.id,
        patient_id=patient.id,
        status="draft",
        billing_name="Cliente Test",
        billing_tax_id=tax_id,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        created_by=(await db.execute(select(User))).scalars().first().id,
    )
    db.add(invoice)
    await db.flush()
    db.add(
        InvoiceItem(
            id=uuid4(),
            clinic_id=clinic.id,
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
    await db.commit()
    return invoice


async def _profile(client: AsyncClient, headers: dict, rfc: str) -> None:
    """The receiver's fiscal profile, without which an RFC is not invoiced."""
    response = await client.put(
        f"/api/v1/sat_cfdi/receivers/{rfc}",
        json={"tax_regime": "612", "tax_zip_code": "06600", "cfdi_use": "D01"},
        headers=headers,
    )
    assert response.status_code == 200, response.text


async def _issue(client: AsyncClient, headers: dict, invoice_id) -> dict:
    response = await client.post(
        f"/api/v1/billing/invoices/{invoice_id}/issue", json={}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _cfdis(db: AsyncSession, invoice_id) -> list[SatCfdi]:
    rows = await db.execute(select(SatCfdi).where(SatCfdi.invoice_id == invoice_id))
    return list(rows.scalars().all())


async def _stamped(db: AsyncSession, invoice_id) -> SatCfdi:
    [cfdi] = await _cfdis(db, invoice_id)
    cfdi.state = "stamped"
    cfdi.uuid = str(uuid4()).upper()
    await db.commit()
    return cfdi


def test_the_hook_is_registered_for_mexico() -> None:
    hook = BillingHookRegistry.get("MX")
    assert isinstance(hook, SatCfdiHook)
    assert hook.cancellation_needs_confirmation


@pytest.mark.asyncio
async def test_an_invoice_needs_a_valid_rfc(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexico: Clinic,
    test_patient: Patient,
) -> None:
    for tax_id in ("", "B12345678", "GOMA80010"):
        invoice = await _draft(db_session, mexico, test_patient, tax_id)
        response = await client.post(
            f"/api/v1/billing/invoices/{invoice.id}/issue", json={}, headers=auth_headers
        )
        assert response.status_code == 400, (tax_id, response.text)
        assert "RFC" in response.text
        assert await _cfdis(db_session, invoice.id) == []


@pytest.mark.asyncio
async def test_issuing_queues_a_pending_cfdi(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexico: Clinic,
    test_patient: Patient,
) -> None:
    public = await _draft(db_session, mexico, test_patient, PUBLIC)
    person = await _draft(db_session, mexico, test_patient, "goma800101ab1")
    await _profile(client, auth_headers, "GOMA800101AB1")

    for invoice in (public, person):
        data = await _issue(client, auth_headers, invoice.id)
        [cfdi] = await _cfdis(db_session, invoice.id)
        assert (cfdi.clinic_id, cfdi.kind, cfdi.state, cfdi.uuid) == (
            mexico.id,
            "I",
            "pending",
            None,
        )
        assert data["compliance_data"]["MX"] == {
            "cfdi_id": str(cfdi.id),
            "state": "pending",
            "severity": "pending",
        }


@pytest.mark.asyncio
async def test_a_credit_note_queues_an_egreso_related_to_the_invoice(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexico: Clinic,
    test_patient: Patient,
) -> None:
    invoice = await _draft(db_session, mexico, test_patient, PUBLIC)
    await _issue(client, auth_headers, invoice.id)
    created = await client.post(
        f"/api/v1/billing/invoices/{invoice.id}/credit-note",
        json={"reason": "Devolución"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    credit_note_id = created.json()["data"]["id"]

    await _issue(client, auth_headers, credit_note_id)

    [egreso] = await _cfdis(db_session, credit_note_id)
    [ingreso] = await _cfdis(db_session, invoice.id)
    assert (egreso.kind, egreso.state, egreso.related_cfdi_id) == ("E", "pending", ingreso.id)


@pytest.mark.asyncio
async def test_the_cfdis_of_an_invoice_are_listed(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexico: Clinic,
    test_patient: Patient,
) -> None:
    invoice = await _draft(db_session, mexico, test_patient, PUBLIC)
    await _issue(client, auth_headers, invoice.id)

    listed = await client.get(f"/api/v1/sat_cfdi/invoices/{invoice.id}/cfdis", headers=auth_headers)
    unknown = await client.get(f"/api/v1/sat_cfdi/invoices/{uuid4()}/cfdis", headers=auth_headers)

    assert listed.status_code == 200, listed.text
    [row] = listed.json()["data"]
    assert (row["kind"], row["state"], row["uuid"]) == ("I", "pending", None)
    assert unknown.json()["data"] == []


# --- Cancelling ----------------------------------------------------------------


async def _cancel(client: AsyncClient, headers: dict, invoice_id, **body):
    return await client.post(
        f"/api/v1/billing/invoices/{invoice_id}/cancel", json=body, headers=headers
    )


@pytest.mark.asyncio
async def test_an_unstamped_invoice_cannot_be_cancelled(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexico: Clinic,
    test_patient: Patient,
) -> None:
    invoice = await _draft(db_session, mexico, test_patient, PUBLIC)
    await _issue(client, auth_headers, invoice.id)

    response = await _cancel(client, auth_headers, invoice.id, reason="02")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "billing.invoice.cancel_refused"


@pytest.mark.asyncio
async def test_the_reason_must_be_one_of_the_sat(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexico: Clinic,
    test_patient: Patient,
) -> None:
    invoice = await _draft(db_session, mexico, test_patient, PUBLIC)
    await _issue(client, auth_headers, invoice.id)
    await _stamped(db_session, invoice.id)

    unknown = await _cancel(client, auth_headers, invoice.id, reason="05")
    no_substitute = await _cancel(client, auth_headers, invoice.id, reason="01")

    for response in (unknown, no_substitute):
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "billing.invoice.cancel_refused"


@pytest.mark.asyncio
async def test_a_cancellation_waits_for_the_sat(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexico: Clinic,
    test_patient: Patient,
) -> None:
    invoice = await _draft(db_session, mexico, test_patient, "GOMA800101AB1")
    substitute = await _draft(db_session, mexico, test_patient, "GOMA800101AB2")
    await _profile(client, auth_headers, "GOMA800101AB1")
    await _profile(client, auth_headers, "GOMA800101AB2")
    await _issue(client, auth_headers, invoice.id)
    await _issue(client, auth_headers, substitute.id)
    await _stamped(db_session, invoice.id)

    unstamped_substitute = await _cancel(
        client, auth_headers, invoice.id, reason="01", substitute_invoice_id=str(substitute.id)
    )
    assert unstamped_substitute.status_code == 422, unstamped_substitute.text

    replacement = await _stamped(db_session, substitute.id)
    response = await _cancel(
        client, auth_headers, invoice.id, reason="01", substitute_invoice_id=str(substitute.id)
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "issued"
    [cfdi] = await _cfdis(db_session, invoice.id)
    await db_session.refresh(cfdi)
    assert (cfdi.state, cfdi.cancel_reason, cfdi.substitute_cfdi_id) == (
        "cancel_requested",
        "01",
        replacement.id,
    )
    assert data["compliance_data"]["MX"] == {
        "cfdi_id": str(cfdi.id),
        "state": "cancel_requested",
        "severity": "pending",
        "uuid": cfdi.uuid,
    }
