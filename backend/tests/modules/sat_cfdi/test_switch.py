"""The SAT module is the clinic's to switch on, and its Facturama account too.

``sat_cfdi`` is an optional module of Budgets & payments (ADR 0066): off
for every clinic until its administrator switches it on, and only for the
``advanced`` and ``clinic`` tiers. Outside a clinic that has it off its
routes answer 404, its hook does not touch billing and its job stamps
nothing. Each clinic keeps its own Facturama credentials — never the
deployment's environment, since every tenant has its own account.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, User
from app.core.email.encryption import decrypt_password
from app.modules.billing.models import Invoice, InvoiceItem, InvoiceSeries
from app.modules.patients.models import Patient
from app.modules.sat_cfdi.models import SatCfdi, SatSettings
from app.modules.sat_cfdi.stamping import stamp_due

from .conftest import FakePac, configure_issuer

SWITCH = "/api/v1/apps/budgets_payments/modules/sat_cfdi"


async def _draft(db: AsyncSession, clinic: Clinic, patient: Patient, tax_id: str) -> Invoice:
    db.add(
        InvoiceSeries(
            id=uuid4(), clinic_id=clinic.id, prefix="FAC", series_type="invoice", is_default=True
        )
    )
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
    return invoice


@pytest.mark.asyncio
async def test_a_clinic_starts_with_the_sat_off(
    client: AsyncClient, auth_headers: dict, test_clinic: Clinic
) -> None:
    apps = (await client.get("/api/v1/apps", headers=auth_headers)).json()["data"]
    budgets = next(app for app in apps if app["name"] == "budgets_payments")

    assert budgets["optional_modules"] == [
        {"name": "sat_cfdi", "enabled": False, "available": True}
    ]
    response = await client.get("/api/v1/sat_cfdi/settings", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tier", "allowed"),
    [
        ("advanced", True),
        ("clinic", True),
        ("basic", False),
        ("medium", False),
        ("clinic_pro", False),
        ("hospital", False),
    ],
)
async def test_only_advanced_and_clinic_may_switch_it_on(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    tier: str,
    allowed: bool,
) -> None:
    test_clinic.account_tier = tier
    await db_session.commit()

    response = await client.post(f"{SWITCH}/enable", headers=auth_headers)

    assert response.status_code == (200 if allowed else 403), response.text


@pytest.mark.asyncio
async def test_with_the_sat_off_billing_issues_as_before(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    test_clinic.settings = {**(test_clinic.settings or {}), "country": "MX"}
    await db_session.commit()
    # Not an RFC: the SAT's hook would refuse it.
    invoice = await _draft(db_session, test_clinic, test_patient, "B12345678")

    response = await client.post(
        f"/api/v1/billing/invoices/{invoice.id}/issue", json={}, headers=auth_headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["compliance_data"] in (None, {})
    rows = await db_session.execute(select(SatCfdi).where(SatCfdi.invoice_id == invoice.id))
    assert rows.scalars().all() == []


@pytest.mark.asyncio
async def test_switched_off_its_pending_cfdis_wait(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexican_clinic: Clinic,
    test_patient: Patient,
    fake_pac: FakePac,
) -> None:
    await configure_issuer(client, auth_headers)
    invoice = await _draft(db_session, mexican_clinic, test_patient, "XAXX010101000")
    issued = await client.post(
        f"/api/v1/billing/invoices/{invoice.id}/issue", json={}, headers=auth_headers
    )
    assert issued.status_code == 200, issued.text

    assert (await client.post(f"{SWITCH}/disable", headers=auth_headers)).status_code == 200
    await stamp_due(now=datetime.now(UTC) + timedelta(hours=1))

    assert fake_pac.stamped == []
    assert (await client.post(f"{SWITCH}/enable", headers=auth_headers)).status_code == 200
    await stamp_due(now=datetime.now(UTC) + timedelta(hours=1))
    assert len(fake_pac.stamped) == 1


@pytest.mark.asyncio
async def test_the_clinic_keeps_its_own_facturama_account(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexican_clinic: Clinic,
) -> None:
    saved = await client.put(
        "/api/v1/sat_cfdi/facturama-credentials",
        json={"environment": "sandbox", "user": "clinica-demo", "password": "secreta"},
        headers=auth_headers,
    )

    assert saved.status_code == 200, saved.text
    facturama = saved.json()["data"]["facturama"]
    assert facturama == {
        "sandbox": {"user": "clinica-demo", "has_password": True},
        "production": {"user": None, "has_password": False},
    }
    assert "secreta" not in saved.text
    stored = (
        await db_session.execute(
            select(SatSettings).where(SatSettings.clinic_id == mexican_clinic.id)
        )
    ).scalar_one()
    assert stored.facturama_sandbox_password_encrypted != "secreta"
    assert decrypt_password(stored.facturama_sandbox_password_encrypted) == "secreta"

    # Changing the user alone keeps the password.
    again = await client.put(
        "/api/v1/sat_cfdi/facturama-credentials",
        json={"environment": "sandbox", "user": "otra-cuenta"},
        headers=auth_headers,
    )
    assert again.json()["data"]["facturama"]["sandbox"] == {
        "user": "otra-cuenta",
        "has_password": True,
    }


@pytest.mark.asyncio
async def test_without_its_facturama_account_the_clinic_cannot_issue(
    client: AsyncClient, auth_headers: dict, mexican_clinic: Clinic
) -> None:
    response = await client.put(
        "/api/v1/sat_cfdi/settings",
        json={
            "tax_regime": "601",
            "expedition_postal_code": "42501",
            "environment": "sandbox",
            "product_code": "85121800",
        },
        headers=auth_headers,
    )

    assert response.json()["data"]["missing"] == (
        "Para facturar ante el SAT, faltan el usuario y la contraseña de Facturama "
        "de la clínica (entorno de pruebas)."
    )
