"""The issuer: the clinic's SAT settings and its CSD.

The RFC and the legal name are the clinic's own (``Clinic.tax_id``,
``Clinic.legal_name``); the module keeps only what the SAT adds — the tax
regime, the postal code of issue, the environment — and the CSD, whose
private key and password are stored encrypted.
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
from app.core.email.encryption import decrypt_bytes, decrypt_password
from app.modules.billing.models import Invoice, InvoiceItem, InvoiceSeries
from app.modules.patients.models import Patient
from app.modules.sat_cfdi.models import SatCertificate

from .conftest import CERTIFICATE_NUMBER, ISSUER_RFC, configure_issuer, make_csd


async def _upload(client: AsyncClient, headers: dict, csd, password: str | None = None):
    return await client.post(
        "/api/v1/sat_cfdi/certificate",
        files={
            "cer": ("csd.cer", csd.cer, "application/octet-stream"),
            "key": ("csd.key", csd.key, "application/octet-stream"),
        },
        data={"password": csd.password if password is None else password},
        headers=headers,
    )


async def _certificates(db: AsyncSession, clinic: Clinic) -> list[SatCertificate]:
    rows = await db.execute(
        select(SatCertificate)
        .where(SatCertificate.clinic_id == clinic.id)
        .order_by(SatCertificate.created_at)
    )
    return list(rows.scalars().all())


# --- Settings -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_settings_show_the_clinic_as_issuer(
    client: AsyncClient, auth_headers: dict, mexican_clinic: Clinic
) -> None:
    empty = await client.get("/api/v1/sat_cfdi/settings", headers=auth_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["data"] == {
        "rfc": ISSUER_RFC,
        "legal_name": "ESCUELA KEMPER URGATE",
        "tax_regime": None,
        "expedition_postal_code": None,
        "environment": "sandbox",
        "product_code": None,
        "unit_code": "E48",
        "stamp_delay_minutes": 30,
        "facturama": {
            "sandbox": {"user": None, "has_password": False},
            "production": {"user": None, "has_password": False},
        },
        "certificate": None,
        "ready": False,
        "missing": (
            "Para facturar ante el SAT, faltan el régimen fiscal y el código postal de expedición."
        ),
    }

    saved = await client.put(
        "/api/v1/sat_cfdi/settings",
        json={"tax_regime": "612", "expedition_postal_code": "06600", "environment": "production"},
        headers=auth_headers,
    )

    assert saved.status_code == 200, saved.text
    data = saved.json()["data"]
    assert (data["tax_regime"], data["expedition_postal_code"], data["environment"]) == (
        "612",
        "06600",
        "production",
    )
    # Settings without a CSD cannot issue.
    assert data["ready"] is False
    assert data["missing"] == (
        "Para facturar ante el SAT, faltan el usuario y la contraseña de Facturama "
        "de la clínica (entorno de producción)."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"tax_regime": "999", "expedition_postal_code": "06600", "environment": "sandbox"},
        {"tax_regime": "612", "expedition_postal_code": "6600", "environment": "sandbox"},
        {"tax_regime": "612", "expedition_postal_code": "06600", "environment": "live"},
    ],
)
async def test_settings_must_be_the_sat_s(
    client: AsyncClient, auth_headers: dict, mexican_clinic: Clinic, body: dict
) -> None:
    response = await client.put("/api/v1/sat_cfdi/settings", json=body, headers=auth_headers)
    assert response.status_code == 422, response.text


# --- The CSD ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_csd_is_stored_encrypted(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexican_clinic: Clinic,
) -> None:
    csd = make_csd()

    response = await _upload(client, auth_headers, csd)

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert (data["certificate_number"], data["rfc"], data["is_active"]) == (
        CERTIFICATE_NUMBER,
        ISSUER_RFC,
        True,
    )
    # Never the key or the password, not even encrypted.
    assert set(data) == {
        "id",
        "certificate_number",
        "rfc",
        "valid_from",
        "valid_until",
        "is_active",
        "created_at",
        "registered_in",
        "registration_error",
    }
    [stored] = await _certificates(db_session, mexican_clinic)
    assert stored.cer == csd.cer
    assert stored.key_encrypted != csd.key
    assert decrypt_bytes(stored.key_encrypted) == csd.key
    assert decrypt_password(stored.password_encrypted) == csd.password


@pytest.mark.asyncio
async def test_a_new_csd_replaces_the_active_one(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexican_clinic: Clinic,
) -> None:
    assert (await _upload(client, auth_headers, make_csd())).status_code == 201
    renewed = make_csd(number="30001000000500003417")
    assert (await _upload(client, auth_headers, renewed)).status_code == 201

    old, new = await _certificates(db_session, mexican_clinic)
    assert (old.is_active, new.is_active) == (False, True)
    assert new.certificate_number == "30001000000500003417"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("csd", "password", "code"),
    [
        (make_csd(), "wrong", "sat_cfdi.certificate.key_invalid"),
        (make_csd(rfc="GOMA800101AB1"), None, "sat_cfdi.certificate.rfc_mismatch"),
        (make_csd(with_rfc=False), None, "sat_cfdi.certificate.not_csd"),
        (make_csd(number="12345"), None, "sat_cfdi.certificate.not_csd"),
        (
            make_csd(
                not_before=datetime.now(UTC) - timedelta(days=400),
                not_after=datetime.now(UTC) - timedelta(days=1),
            ),
            None,
            "sat_cfdi.certificate.not_valid_now",
        ),
    ],
)
async def test_a_csd_that_cannot_sign_for_the_clinic_is_refused(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexican_clinic: Clinic,
    csd,
    password: str | None,
    code: str,
) -> None:
    response = await _upload(client, auth_headers, csd, password)

    assert response.json()["code"] == code, response.text
    assert await _certificates(db_session, mexican_clinic) == []


@pytest.mark.asyncio
async def test_a_key_must_belong_to_its_certificate(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexican_clinic: Clinic,
) -> None:
    one, other = make_csd(), make_csd()
    one.key = other.key

    response = await _upload(client, auth_headers, one)

    assert response.json()["code"] == "sat_cfdi.certificate.key_mismatch", response.text


@pytest.mark.asyncio
async def test_a_file_that_is_no_certificate_is_refused(
    client: AsyncClient, auth_headers: dict, mexican_clinic: Clinic
) -> None:
    csd = make_csd()
    csd.cer = b"not a certificate"

    response = await _upload(client, auth_headers, csd)

    assert response.json()["code"] == "sat_cfdi.certificate.unreadable", response.text


@pytest.mark.asyncio
async def test_the_settings_are_ready_with_a_valid_csd(
    client: AsyncClient, auth_headers: dict, mexican_clinic: Clinic
) -> None:
    await configure_issuer(client, auth_headers)

    data = (await client.get("/api/v1/sat_cfdi/settings", headers=auth_headers)).json()["data"]

    assert (data["ready"], data["missing"]) == (True, None)
    assert data["certificate"]["certificate_number"] == CERTIFICATE_NUMBER


# --- Issuing needs the issuer ---------------------------------------------------------


@pytest.mark.asyncio
async def test_an_invoice_cannot_be_issued_before_the_issuer_is_ready(
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
        billing_name="Público en general",
        billing_tax_id="XAXX010101000",
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

    refused = await client.post(
        f"/api/v1/billing/invoices/{invoice.id}/issue", json={}, headers=auth_headers
    )
    assert refused.status_code == 400, refused.text
    assert "SAT" in refused.text

    await configure_issuer(client, auth_headers)
    issued = await client.post(
        f"/api/v1/billing/invoices/{invoice.id}/issue", json={}, headers=auth_headers
    )
    assert issued.status_code == 200, issued.text
