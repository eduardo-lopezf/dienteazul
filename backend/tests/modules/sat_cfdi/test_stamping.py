"""The stamping job: pending ingreso CFDIs go to Facturama after a delay.

Billing records a payment after the invoice is issued, so the job waits
(``stamp_delay_minutes``, 30 by default) and then decides: paid in full →
``PUE`` with the form of the largest payment; otherwise ``PPD`` with
``99``. ``Folio`` and ``Date`` are fixed on the first attempt and sent
unchanged on every retry — Facturama tells operations apart by them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, User
from app.modules.billing.models import Invoice, InvoiceItem, InvoiceSeries
from app.modules.patients.models import Patient
from app.modules.sat_cfdi.models import SatCfdi
from app.modules.sat_cfdi.pac import PacError
from app.modules.sat_cfdi.stamping import stamp_due

from .conftest import FakePac, configure_issuer


def _later() -> datetime:
    """Past the stamping delay, counted from now: a module-level constant
    goes stale when the suite runs for hours."""
    return datetime.now(UTC) + timedelta(hours=1)


@pytest_asyncio.fixture
async def ready(client: AsyncClient, auth_headers: dict, db_session: AsyncSession, mexican_clinic):
    db_session.add(
        InvoiceSeries(
            id=uuid4(),
            clinic_id=mexican_clinic.id,
            prefix="FAC",
            series_type="invoice",
            is_default=True,
        )
    )
    await db_session.commit()
    await configure_issuer(client, auth_headers)
    return mexican_clinic


async def _issued(
    client: AsyncClient,
    headers: dict,
    db: AsyncSession,
    clinic: Clinic,
    patient: Patient,
    *,
    tax_id: str = "XAXX010101000",
) -> Invoice:
    invoice = Invoice(
        id=uuid4(),
        clinic_id=clinic.id,
        patient_id=patient.id,
        status="draft",
        billing_name="Ana Gómez",
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
    response = await client.post(
        f"/api/v1/billing/invoices/{invoice.id}/issue", json={}, headers=headers
    )
    assert response.status_code == 200, response.text
    await db.refresh(invoice)
    return invoice


async def _pay(client: AsyncClient, headers: dict, invoice: Invoice, amount: str, method: str):
    response = await client.post(
        f"/api/v1/billing/invoices/{invoice.id}/payments",
        json={"amount": amount, "method": method, "payment_date": date.today().isoformat()},
        headers=headers,
    )
    assert response.status_code == 201, response.text


async def _cfdi(db: AsyncSession, invoice: Invoice) -> SatCfdi:
    """The invoice's CFDI as the job left it (it commits in its own session)."""
    query = (
        select(SatCfdi)
        .where(SatCfdi.invoice_id == invoice.id)
        .execution_options(populate_existing=True)
    )
    [row] = (await db.execute(query)).scalars().all()
    return row


@pytest.mark.asyncio
async def test_a_cfdi_waits_for_the_delay(
    client, auth_headers, db_session, ready, test_patient, fake_pac: FakePac
) -> None:
    invoice = await _issued(client, auth_headers, db_session, ready, test_patient)

    await stamp_due()

    assert fake_pac.stamped == []
    assert (await _cfdi(db_session, invoice)).state == "pending"


@pytest.mark.asyncio
async def test_an_unpaid_invoice_is_stamped_ppd(
    client, auth_headers, db_session, ready, test_patient, fake_pac: FakePac
) -> None:
    invoice = await _issued(client, auth_headers, db_session, ready, test_patient)

    await stamp_due(now=_later())

    [payload] = fake_pac.stamped
    assert (payload["PaymentMethod"], payload["PaymentForm"]) == ("PPD", "99")
    assert payload["Folio"] == invoice.invoice_number
    assert payload["Receiver"] == {
        "Rfc": "XAXX010101000",
        "Name": "Ana Gómez",
        "FiscalRegime": "616",
        "TaxZipCode": "42501",
        "CfdiUse": "S01",
    }
    cfdi = await _cfdi(db_session, invoice)
    assert (cfdi.state, cfdi.uuid, cfdi.pac_id) == ("stamped", fake_pac.uuid, "FAKE-1")
    assert cfdi.xml == "<cfdi:Comprobante/>"
    assert cfdi.stamped_at is not None
    assert (cfdi.payment_method, cfdi.payment_form) == ("PPD", "99")
    await db_session.refresh(invoice)
    assert invoice.compliance_data["MX"] == {
        "cfdi_id": str(cfdi.id),
        "state": "stamped",
        "severity": "ok",
        "uuid": fake_pac.uuid,
    }


@pytest.mark.asyncio
async def test_a_paid_invoice_is_stamped_pue_with_the_largest_payment(
    client, auth_headers, db_session, ready, test_patient, fake_pac: FakePac
) -> None:
    invoice = await _issued(client, auth_headers, db_session, ready, test_patient)
    await _pay(client, auth_headers, invoice, "30.00", "cash")
    await _pay(client, auth_headers, invoice, "70.00", "card")

    await stamp_due(now=_later())

    [payload] = fake_pac.stamped
    assert (payload["PaymentMethod"], payload["PaymentForm"]) == ("PUE", "04")


@pytest.mark.asyncio
async def test_a_retry_sends_the_same_folio_and_date(
    client, auth_headers, db_session, ready, test_patient, fake_pac: FakePac
) -> None:
    invoice = await _issued(client, auth_headers, db_session, ready, test_patient)
    fake_pac.fail = PacError("Facturama no respondió", transient=True)

    await stamp_due(now=_later())

    cfdi = await _cfdi(db_session, invoice)
    assert (cfdi.state, cfdi.attempts, cfdi.last_error) == ("pending", 1, "Facturama no respondió")
    assert cfdi.next_attempt_at is not None
    first_date = cfdi.cfdi_date

    # Not before its next attempt.
    fake_pac.fail = None
    await stamp_due(now=_later())
    assert fake_pac.stamped == []

    await stamp_due(now=_later() + timedelta(hours=2))
    [payload] = fake_pac.stamped
    assert payload["Date"] == first_date
    cfdi = await _cfdi(db_session, invoice)
    assert (cfdi.state, cfdi.attempts, cfdi.last_error) == ("stamped", 2, None)


@pytest.mark.asyncio
async def test_a_cfdi_the_sat_refuses_is_rejected(
    client, auth_headers, db_session, ready, test_patient, fake_pac: FakePac
) -> None:
    invoice = await _issued(client, auth_headers, db_session, ready, test_patient)
    fake_pac.fail = PacError("Facturama lo rechazó: CFDI40147", transient=False)

    await stamp_due(now=_later())

    cfdi = await _cfdi(db_session, invoice)
    assert (cfdi.state, cfdi.last_error) == ("rejected", "Facturama lo rechazó: CFDI40147")
    await db_session.refresh(invoice)
    assert invoice.compliance_data["MX"]["severity"] == "error"

    # Rejected stays rejected: nothing is sent again by itself.
    fake_pac.fail = None
    await stamp_due(now=_later() + timedelta(hours=5))
    assert fake_pac.stamped == []


@pytest.mark.asyncio
async def test_the_delay_is_the_clinic_s(
    client, auth_headers, db_session, ready, test_patient, fake_pac: FakePac
) -> None:
    response = await client.put(
        "/api/v1/sat_cfdi/settings",
        json={
            "tax_regime": "601",
            "expedition_postal_code": "42501",
            "environment": "sandbox",
            "product_code": "85121800",
            "unit_code": "E48",
            "stamp_delay_minutes": 0,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    invoice = await _issued(client, auth_headers, db_session, ready, test_patient)

    await stamp_due()

    assert len(fake_pac.stamped) == 1
    assert (await _cfdi(db_session, invoice)).state == "stamped"


@pytest.mark.asyncio
async def test_only_ingresos_are_stamped_so_far(
    client, auth_headers, db_session, ready, test_patient, fake_pac: FakePac
) -> None:
    invoice = await _issued(client, auth_headers, db_session, ready, test_patient)
    await db_session.execute(
        update(SatCfdi).where(SatCfdi.invoice_id == invoice.id).values(kind="E")
    )
    await db_session.commit()

    await stamp_due(now=_later())

    assert fake_pac.stamped == []
