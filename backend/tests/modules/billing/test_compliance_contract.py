"""Billing tells a compliance hook of every fiscal change (ADR 0067).

Cancelling an issued invoice, with and without a hook; a hook that refuses
or that confirms later; the substitute invoice; a payment reaching the
hook; and the period read the SAT's global invoice needs.

The hook here is a recording fake registered for a made-up country
(``ZZ``), so nothing depends on a real compliance module.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, User
from app.core.events import EventType
from app.modules.billing import workflow as workflow_mod
from app.modules.billing.hooks import BillingComplianceHook, BillingHookRegistry
from app.modules.billing.models import Invoice, InvoiceHistory, InvoiceItem, InvoiceSeries
from app.modules.billing.service import InvoiceService
from app.modules.billing.workflow import InvoiceWorkflowService
from app.modules.patients.models import Patient

COUNTRY = "ZZ"


class _RecordingHook(BillingComplianceHook):
    def __init__(self) -> None:
        self.refuse_cancel: str | None = None
        self.confirms_later = False
        self.cancelled: list[tuple[str, Any]] = []
        self.payments: list[tuple[Decimal, str]] = []

    @property
    def country_code(self) -> str:
        return COUNTRY

    @property
    def cancellation_needs_confirmation(self) -> bool:
        return self.confirms_later

    async def before_cancel(self, invoice, reason, substitute, db):
        if self.refuse_cancel:
            return False, self.refuse_cancel
        return True, None

    async def on_invoice_cancelled(self, invoice, reason, substitute, cancelled_by, db):
        self.cancelled.append((reason, substitute.id if substitute else None))
        return {COUNTRY: {"cancellation": "requested"}}

    async def on_payment_recorded(self, invoice, link, db):
        self.payments.append((link.amount, invoice.status))
        return {COUNTRY: {"payments": len(self.payments)}}


@pytest_asyncio.fixture
async def hook(db_session: AsyncSession, test_clinic: Clinic):
    recording = _RecordingHook()
    BillingHookRegistry.register(recording)
    test_clinic.settings = {**(test_clinic.settings or {}), "country": COUNTRY}
    await db_session.commit()
    yield recording
    BillingHookRegistry.unregister(COUNTRY)


@pytest.fixture
def published(monkeypatch) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        workflow_mod.event_bus,
        "publish_after_commit",
        lambda db, event, payload: events.append((event, payload)),
    )
    return events


async def _user_id(db: AsyncSession):
    return (await db.execute(select(User))).scalars().first().id


async def _series(db: AsyncSession, clinic: Clinic) -> None:
    exists = (
        await db.execute(
            select(InvoiceSeries).where(
                InvoiceSeries.clinic_id == clinic.id, InvoiceSeries.series_type == "invoice"
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(
            InvoiceSeries(
                id=uuid4(),
                clinic_id=clinic.id,
                prefix="FAC",
                series_type="invoice",
                is_default=True,
            )
        )
        await db.flush()


async def _draft(
    db: AsyncSession, clinic: Clinic, patient: Patient, *, tax_id: str = "XAXX010101000"
) -> Invoice:
    await _series(db, clinic)
    invoice = Invoice(
        id=uuid4(),
        clinic_id=clinic.id,
        patient_id=patient.id,
        status="draft",
        billing_name="Cliente Test",
        billing_tax_id=tax_id,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        created_by=await _user_id(db),
    )
    db.add(invoice)
    await db.flush()
    db.add(
        InvoiceItem(
            id=uuid4(),
            clinic_id=clinic.id,
            invoice_id=invoice.id,
            description="Servicio",
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


async def _issued(
    client: AsyncClient,
    headers: dict,
    db: AsyncSession,
    clinic: Clinic,
    patient: Patient,
    *,
    issue_date: date | None = None,
    tax_id: str = "XAXX010101000",
) -> Invoice:
    invoice = await _draft(db, clinic, patient, tax_id=tax_id)
    body = {"issue_date": issue_date.isoformat()} if issue_date else {}
    response = await client.post(
        f"/api/v1/billing/invoices/{invoice.id}/issue", json=body, headers=headers
    )
    assert response.status_code == 200, response.text
    return invoice


async def _cancel(client: AsyncClient, headers: dict, invoice_id, **body):
    return await client.post(
        f"/api/v1/billing/invoices/{invoice_id}/cancel",
        json={"reason": "02", **body},
        headers=headers,
    )


# --- Cancelling, no hook --------------------------------------------------


@pytest.mark.asyncio
async def test_without_a_hook_cancelling_marks_the_invoice_cancelled(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
    published: list,
) -> None:
    invoice = await _issued(client, auth_headers, db_session, test_clinic, test_patient)

    response = await _cancel(client, auth_headers, invoice.id)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "cancelled"
    history = (
        (
            await db_session.execute(
                select(InvoiceHistory).where(
                    InvoiceHistory.invoice_id == invoice.id, InvoiceHistory.action == "cancelled"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(history) == 1
    assert history[0].new_state["reason"] == "02"
    cancelled = [payload for event, payload in published if event == EventType.INVOICE_CANCELLED]
    assert cancelled == [
        {
            "clinic_id": str(test_clinic.id),
            "invoice_id": str(invoice.id),
            "patient_id": str(test_patient.id),
            "invoice_number": cancelled[0]["invoice_number"],
            "reason": "02",
            "substitute_invoice_id": None,
            "occurred_at": cancelled[0]["occurred_at"],
        }
    ]
    assert cancelled[0]["invoice_number"]


@pytest.mark.asyncio
async def test_a_draft_cannot_be_cancelled(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    invoice = await _draft(db_session, test_clinic, test_patient)

    response = await _cancel(client, auth_headers, invoice.id)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "billing.invoice.cancel_status_invalid"


@pytest.mark.asyncio
async def test_the_substitute_must_be_another_invoice_of_the_clinic(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    invoice = await _issued(client, auth_headers, db_session, test_clinic, test_patient)

    unknown = await _cancel(client, auth_headers, invoice.id, substitute_invoice_id=str(uuid4()))
    itself = await _cancel(client, auth_headers, invoice.id, substitute_invoice_id=str(invoice.id))

    for response in (unknown, itself):
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "billing.invoice.substitute_invalid"


# --- Cancelling, with a hook ----------------------------------------------


@pytest.mark.asyncio
async def test_a_hook_can_refuse_the_cancellation(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
    hook: _RecordingHook,
) -> None:
    invoice = await _issued(client, auth_headers, db_session, test_clinic, test_patient)
    hook.refuse_cancel = "Reason 01 needs a substitute"

    response = await _cancel(client, auth_headers, invoice.id)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "billing.invoice.cancel_refused"
    assert "Reason 01 needs a substitute" in response.text
    assert hook.cancelled == []
    await db_session.refresh(invoice)
    assert invoice.status == "issued"


@pytest.mark.asyncio
async def test_a_hook_that_confirms_later_leaves_the_invoice_issued(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
    hook: _RecordingHook,
    published: list,
) -> None:
    invoice = await _issued(client, auth_headers, db_session, test_clinic, test_patient)
    substitute = await _issued(client, auth_headers, db_session, test_clinic, test_patient)
    hook.confirms_later = True

    response = await _cancel(
        client, auth_headers, invoice.id, reason="01", substitute_invoice_id=str(substitute.id)
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "issued"
    assert data["compliance_data"][COUNTRY] == {"cancellation": "requested"}
    assert hook.cancelled == [("01", substitute.id)]
    assert not [e for e, _ in published if e == EventType.INVOICE_CANCELLED]

    # The authority confirms: the module asks billing to mark it.
    await db_session.refresh(invoice)
    await InvoiceWorkflowService.mark_cancelled(
        db_session,
        invoice,
        await _user_id(db_session),
        reason="01",
        substitute_invoice_id=substitute.id,
    )
    await db_session.commit()

    assert invoice.status == "cancelled"
    [(_, payload)] = [(e, p) for e, p in published if e == EventType.INVOICE_CANCELLED]
    assert payload["substitute_invoice_id"] == str(substitute.id)


@pytest.mark.asyncio
async def test_a_hook_that_needs_no_confirmation_cancels_at_once(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
    hook: _RecordingHook,
) -> None:
    invoice = await _issued(client, auth_headers, db_session, test_clinic, test_patient)

    response = await _cancel(client, auth_headers, invoice.id)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "cancelled"
    assert data["compliance_data"][COUNTRY] == {"cancellation": "requested"}
    assert hook.cancelled == [("02", None)]


# --- Payments ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_payment_reaches_the_hook(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
    hook: _RecordingHook,
) -> None:
    invoice = await _issued(client, auth_headers, db_session, test_clinic, test_patient)

    response = await client.post(
        f"/api/v1/billing/invoices/{invoice.id}/payments",
        json={"amount": "40.00", "method": "card", "payment_date": date.today().isoformat()},
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    # The hook sees the status after the payment.
    assert hook.payments == [(Decimal("40.00"), "partial")]
    await db_session.refresh(invoice)
    assert invoice.compliance_data[COUNTRY] == {"payments": 1}


# --- The period read ----------------------------------------------------------


@pytest.mark.asyncio
async def test_issued_invoices_of_a_period(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    in_period = await _issued(
        client, auth_headers, db_session, test_clinic, test_patient, issue_date=date(2026, 10, 5)
    )
    with_tax_id = await _issued(
        client,
        auth_headers,
        db_session,
        test_clinic,
        test_patient,
        issue_date=date(2026, 10, 20),
        tax_id="GOMA800101AB1",
    )
    await _issued(
        client, auth_headers, db_session, test_clinic, test_patient, issue_date=date(2026, 11, 2)
    )
    cancelled = await _issued(
        client, auth_headers, db_session, test_clinic, test_patient, issue_date=date(2026, 10, 9)
    )
    assert (await _cancel(client, auth_headers, cancelled.id)).status_code == 200
    await _draft(db_session, test_clinic, test_patient)

    every = await InvoiceService.list_issued_in_period(
        db_session, test_clinic.id, date(2026, 10, 1), date(2026, 10, 31)
    )
    public = await InvoiceService.list_issued_in_period(
        db_session,
        test_clinic.id,
        date(2026, 10, 1),
        date(2026, 10, 31),
        billing_tax_id="XAXX010101000",
    )
    elsewhere = await InvoiceService.list_issued_in_period(
        db_session, uuid4(), date(2026, 10, 1), date(2026, 10, 31)
    )

    assert [i.id for i in every] == [in_period.id, with_tax_id.id]
    assert [i.id for i in public] == [in_period.id]
    assert elsewhere == []


# --- Only a live module's hook answers ------------------------------------------


class _OwnedHook(BillingComplianceHook):
    def __init__(self, module: str) -> None:
        self._module = module

    @property
    def country_code(self) -> str:
        return COUNTRY

    @property
    def module_name(self) -> str:
        return self._module


def test_a_hook_answers_only_while_its_module_is_live() -> None:
    clinic = Clinic(settings={"country": COUNTRY})
    try:
        BillingHookRegistry.register(_OwnedHook("billing"))
        assert BillingHookRegistry.get_for_clinic(clinic) is not None
        assert BillingHookRegistry.get(COUNTRY) is not None

        # Discovered but switched off — or archived (ADR 0035, 0038).
        BillingHookRegistry.register(_OwnedHook("no_such_module"))
        assert BillingHookRegistry.get_for_clinic(clinic) is None
        assert BillingHookRegistry.get(COUNTRY) is None
        assert not BillingHookRegistry.is_registered(COUNTRY)
    finally:
        BillingHookRegistry.unregister(COUNTRY)


def test_a_hook_answers_only_a_clinic_that_has_its_module() -> None:
    """An optional module (ADR 0066) is outside a clinic that has not
    switched it on, and so is its hook."""
    BillingHookRegistry.register(_OwnedHook("sat_cfdi"))
    try:
        off = Clinic(settings={"country": COUNTRY}, account_tier="clinic", modules=None)
        on = Clinic(settings={"country": COUNTRY}, account_tier="clinic", modules=["sat_cfdi"])
        wrong_tier = Clinic(
            settings={"country": COUNTRY}, account_tier="basic", modules=["sat_cfdi"]
        )

        assert BillingHookRegistry.get_for_clinic(off) is None
        assert BillingHookRegistry.get_for_clinic(on) is not None
        assert BillingHookRegistry.get_for_clinic(wrong_tier) is None
    finally:
        BillingHookRegistry.unregister(COUNTRY)
