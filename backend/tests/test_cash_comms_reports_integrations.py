"""Cash, Communications and Reports run with what they integrate off (ADR 0037).

None of the three requires another App. While one they read is off:

- Cash: the arqueo counts only the till's movements without Payments;
  Liquidations reads what was issued and calculates nothing new without
  Payments or Professionals.
- Communications: nothing is sent to a patient without Patients.
- Reports: a section whose App is off answers 404; without Patients the
  figures stay and the names go.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.plugins.registry import module_registry
from app.core.utils.clinic_time import clinic_date
from app.modules.notifications.gateway import NotificationGateway
from app.modules.notifications.integrations import PATIENTS_UNAVAILABLE
from app.modules.patients.models import Patient
from app.modules.payments.models import Payment, PaymentAllocation
from app.modules.professionals.models import Professional

TODAY = clinic_date(datetime.now(UTC), "America/Mexico_City")

MANIFESTS = {
    "cashbox": {"payments"},
    "liquidations": {"payments", "professionals"},
    "notifications": {"patients", "agenda", "budget", "billing", "catalog", "professionals"},
    "whatsapp_kapso": {"patients"},
    "reports": {"patients", "agenda", "catalog", "budget", "billing", "payments", "professionals"},
}


@contextmanager
def off(*names: str) -> Iterator[None]:
    was_active = [name for name in names if module_registry.is_installed(name)]
    for name in names:
        module_registry.deactivate(name)
    try:
        yield
    finally:
        for name in was_active:
            module_registry.activate(name)


def test_none_of_them_requires_what_it_integrates() -> None:
    for name, integrated in MANIFESTS.items():
        manifest = module_registry.get(name).manifest
        assert not set(manifest.get("depends", [])) & integrated, name
        assert set(manifest["integrates"]) == integrated, name


@pytest.fixture
async def world(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic: Clinic
) -> dict:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = UUID(me.json()["data"]["user"]["id"])
    patient = Patient(
        id=uuid4(),
        clinic_id=test_clinic.id,
        first_name="Rosa",
        last_name="Ibarra",
        email="rosa@example.com",
    )
    professional = Professional(
        id=uuid4(),
        clinic_id=test_clinic.id,
        first_name="Dra",
        last_name="Lima",
        professional_type="dentist",
        is_active=True,
    )
    db_session.add_all([patient, professional])
    await db_session.flush()
    payment = Payment(
        id=uuid4(),
        clinic_id=test_clinic.id,
        patient_id=patient.id,
        amount=Decimal("50.00"),
        currency=test_clinic.currency,
        method="cash",
        payment_date=TODAY,
        recorded_by=user_id,
    )
    db_session.add(payment)
    await db_session.flush()
    db_session.add(
        PaymentAllocation(
            id=uuid4(),
            clinic_id=test_clinic.id,
            payment_id=payment.id,
            target_type="on_account",
            amount=Decimal("50.00"),
            created_by=user_id,
        )
    )
    await db_session.commit()
    return {
        "clinic_id": test_clinic.id,
        "patient": patient,
        "professional_id": str(professional.id),
    }


async def _position(client: AsyncClient, headers: dict) -> dict:
    response = await client.get(
        "/api/v1/cashbox/position",
        params={"business_date": TODAY.isoformat()},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_the_till_counts_only_its_own_movements_without_payments(
    client: AsyncClient, auth_headers: dict, world: dict
) -> None:
    assert Decimal(str((await _position(client, auth_headers))["cash_collected"])) == Decimal("50")

    with off("payments"):
        position = await _position(client, auth_headers)
        assert Decimal(str(position["cash_collected"])) == 0
        assert position["collected_by_method"] == []


@pytest.mark.asyncio
async def test_settlements_are_not_calculated_without_payments_or_professionals(
    client: AsyncClient, auth_headers: dict, world: dict
) -> None:
    period = {"date_from": TODAY.isoformat(), "date_to": TODAY.isoformat()}
    for missing in ("payments", "professionals"):
        with off(missing):
            preview = await client.get(
                "/api/v1/liquidations/preview",
                params={"professional_id": world["professional_id"], **period},
                headers=auth_headers,
            )
            assert preview.status_code == 422, missing
            commission = await client.put(
                f"/api/v1/liquidations/commissions/{world['professional_id']}",
                json={"basis": "collected", "percent": "40"},
                headers=auth_headers,
            )
            assert commission.status_code == 422, missing
            issued = await client.get("/api/v1/liquidations", params=period, headers=auth_headers)
            assert issued.status_code == 200, issued.text


@pytest.mark.asyncio
async def test_nothing_is_sent_to_a_patient_without_patients(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, world: dict
) -> None:
    patient = world["patient"]
    with off("patients"):
        message = await NotificationGateway.enqueue(
            db_session,
            world["clinic_id"],
            "appointment_confirmation",
            context={},
            patient_id=patient.id,
            to_address=patient.email,
            force_send=True,
        )
        assert message is not None
        assert (message.status, message.error_message) == ("skipped", "patients_unavailable")

        manual = await client.post(
            "/api/v1/notifications/send",
            json={"notification_type": "welcome", "patient_id": str(patient.id)},
            headers=auth_headers,
        )
        assert manual.status_code == 400
        assert manual.json()["message"] == PATIENTS_UNAVAILABLE

        settings = await client.get("/api/v1/notifications/settings", headers=auth_headers)
        assert settings.status_code == 200, settings.text


@pytest.mark.asyncio
async def test_a_report_answers_only_while_its_app_runs(
    client: AsyncClient, auth_headers: dict, world: dict
) -> None:
    period = {"date_from": TODAY.isoformat(), "date_to": TODAY.isoformat()}
    sections = {
        "billing": "/api/v1/reports/billing/summary",
        "budget": "/api/v1/reports/budgets/summary",
        "agenda": "/api/v1/reports/scheduling/summary",
    }
    for module, path in sections.items():
        assert (await client.get(path, params=period, headers=auth_headers)).status_code == 200
        with off(module):
            hidden = await client.get(path, params=period, headers=auth_headers)
            assert hidden.status_code == 404, module

    with off("patients"):
        overdue = await client.get("/api/v1/reports/billing/overdue", headers=auth_headers)
        assert overdue.status_code == 200, overdue.text
