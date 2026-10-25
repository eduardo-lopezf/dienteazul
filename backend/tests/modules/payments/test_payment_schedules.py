"""Agreed payment schedules.

The earned ledger answers "what is owed for work already done". For a 19.000 €
orthognathic case that reads 0 € for months while the clinic collects exactly
on plan, because the money is agreed up front. A schedule records that
agreement — and settles against the *same* payments, so the two views must
never be added together.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership
from app.modules.patients.models import Patient
from app.modules.payments.errors import ERROR_CATALOG
from app.modules.payments.models import PatientEarnedEntry, Payment, PaymentAllocation

BASE = "/api/v1/payments"


@pytest.fixture
async def ctx(db_session: AsyncSession, auth_headers: dict, client: AsyncClient) -> dict:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = UUID(me.json()["data"]["user"]["id"])
    clinic = Clinic(
        id=uuid4(),
        name="Schedule Clinic",
        tax_id="A28002222",
        timezone="Europe/Madrid",
        currency="EUR",
        settings={},
        account_tier="clinic",
    )
    db_session.add(clinic)
    await db_session.flush()
    db_session.add(ClinicMembership(id=uuid4(), clinic_id=clinic.id, user_id=user_id, role="admin"))
    patient = Patient(id=uuid4(), clinic_id=clinic.id, first_name="Eva", last_name="Plazo")
    db_session.add(patient)
    await db_session.commit()
    return {"clinic_id": clinic.id, "patient_id": patient.id, "user_id": user_id}


async def _pay(db: AsyncSession, ctx: dict, amount: str) -> None:
    payment = Payment(
        id=uuid4(),
        clinic_id=ctx["clinic_id"],
        patient_id=ctx["patient_id"],
        amount=Decimal(amount),
        currency="EUR",
        method="cash",
        payment_date=date.today(),
        recorded_by=ctx["user_id"],
    )
    db.add(payment)
    await db.flush()
    db.add(
        PaymentAllocation(
            id=uuid4(),
            clinic_id=ctx["clinic_id"],
            payment_id=payment.id,
            target_type="on_account",
            amount=Decimal(amount),
            created_by=ctx["user_id"],
        )
    )
    await db.commit()


async def _create(client: AsyncClient, auth_headers: dict, ctx: dict, instalments: list[dict]):
    return await client.post(
        f"{BASE}/schedules",
        headers=auth_headers,
        json={"patient_id": str(ctx["patient_id"]), "instalments": instalments},
    )


@pytest.mark.asyncio
async def test_payments_cover_the_instalments_in_order(client, auth_headers, ctx, db_session):
    """8.000 against 5.706 / 7.608 / 5.706: first settled, second half covered."""
    r = await _create(
        client,
        auth_headers,
        ctx,
        [
            {"label": "Anticipo", "due_date": "2099-01-01", "amount": "5706.00"},
            {"label": "Antes de cirugía", "due_date": "2099-06-01", "amount": "7608.00"},
            {"label": "Al alta", "amount": "5706.00"},
        ],
    )
    assert r.status_code == 201, r.text
    schedule_id = r.json()["data"]["id"]

    await _pay(db_session, ctx, "8000.00")

    body = (await client.get(f"{BASE}/schedules/{schedule_id}", headers=auth_headers)).json()[
        "data"
    ]
    assert body["collected"] == "8000.00"
    assert body["pending"] == "11020.00"
    statuses = [i["status"] for i in body["instalments"]]
    assert statuses == ["paid", "partial", "pending"]
    assert body["instalments"][1]["pending"] == "5314.00"


@pytest.mark.asyncio
async def test_a_past_due_date_is_overdue(client, auth_headers, ctx):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    r = await _create(
        client,
        auth_headers,
        ctx,
        [
            {"label": "Vencida", "due_date": yesterday, "amount": "500.00"},
            {"label": "Futura", "due_date": "2099-01-01", "amount": "500.00"},
        ],
    )
    body = r.json()["data"]
    assert [i["status"] for i in body["instalments"]] == ["overdue", "pending"]
    assert body["overdue"] == "500.00"


@pytest.mark.asyncio
async def test_a_milestone_without_a_date_is_never_overdue(client, auth_headers, ctx):
    """ "Before surgery" is a real milestone with no date. It cannot be late."""
    r = await _create(client, auth_headers, ctx, [{"label": "Al alta", "amount": "500.00"}])
    body = r.json()["data"]
    assert body["instalments"][0]["status"] == "pending"
    assert body["overdue"] == "0"


@pytest.mark.asyncio
async def test_paying_beyond_the_agreement_is_reported_not_lost(
    client, auth_headers, ctx, db_session
):
    r = await _create(client, auth_headers, ctx, [{"label": "Único", "amount": "500.00"}])
    schedule_id = r.json()["data"]["id"]
    await _pay(db_session, ctx, "800.00")

    body = (await client.get(f"{BASE}/schedules/{schedule_id}", headers=auth_headers)).json()[
        "data"
    ]
    assert body["pending"] == "0.00"
    assert body["unapplied"] == "300.00"


@pytest.mark.asyncio
async def test_the_schedule_and_the_earned_ledger_are_separate_views(
    client, auth_headers, ctx, db_session
):
    """The same payment settles both. They are never summed.

    A deposit collected before any treatment leaves the earned view at zero
    and the schedule at "anticipo pagado" — both correct, and adding them
    would double the patient's bill.
    """
    r = await _create(client, auth_headers, ctx, [{"label": "Anticipo", "amount": "500.00"}])
    schedule_id = r.json()["data"]["id"]
    await _pay(db_session, ctx, "500.00")

    schedule = (await client.get(f"{BASE}/schedules/{schedule_id}", headers=auth_headers)).json()[
        "data"
    ]
    assert schedule["instalments"][0]["status"] == "paid"

    pending = await client.get(
        f"{BASE}/patients/{ctx['patient_id']}/pending-charges", headers=auth_headers
    )
    assert pending.json()["data"] == []

    # Now the work happens: 500 earned, and it is already covered.
    db_session.add(
        PatientEarnedEntry(
            id=uuid4(),
            clinic_id=ctx["clinic_id"],
            patient_id=ctx["patient_id"],
            treatment_id=uuid4(),
            amount=Decimal("500.00"),
            performed_at=datetime.now(UTC),
            source_event="test",
        )
    )
    await db_session.commit()

    pending = await client.get(
        f"{BASE}/patients/{ctx['patient_id']}/pending-charges", headers=auth_headers
    )
    assert pending.json()["data"] == []


@pytest.mark.asyncio
async def test_an_instalment_of_zero_is_refused(client, auth_headers, ctx):
    r = await _create(client, auth_headers, ctx, [{"label": "Nada", "amount": "0"}])
    assert r.status_code == 422
    definition = ERROR_CATALOG["payments.schedule.instalment_amount_invalid"]
    assert r.json()["code"] == definition.code
    assert r.json()["category"] == definition.category.value
    assert r.json()["reference"] == r.headers["x-request-id"]


@pytest.mark.asyncio
async def test_cancelling_hides_the_schedule_without_erasing_it(client, auth_headers, ctx):
    r = await _create(client, auth_headers, ctx, [{"label": "Único", "amount": "500.00"}])
    schedule_id = r.json()["data"]["id"]

    assert (
        await client.delete(f"{BASE}/schedules/{schedule_id}", headers=auth_headers)
    ).status_code == 204

    listed = await client.get(
        f"{BASE}/schedules?patient_id={ctx['patient_id']}", headers=auth_headers
    )
    assert all(s["id"] != schedule_id for s in listed.json()["data"])

    with_cancelled = await client.get(
        f"{BASE}/schedules?patient_id={ctx['patient_id']}&include_cancelled=true",
        headers=auth_headers,
    )
    assert any(s["id"] == schedule_id for s in with_cancelled.json()["data"])


@pytest.mark.asyncio
async def test_a_patient_from_another_clinic_is_refused(client, auth_headers, ctx):
    r = await client.post(
        f"{BASE}/schedules",
        headers=auth_headers,
        json={"patient_id": str(uuid4()), "instalments": [{"amount": "100.00"}]},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_a_budget_backed_schedule_ignores_other_budgets(
    client, auth_headers, ctx, db_session
):
    """Money that paid a different, closed budget is not a head start here.

    The case that caught this: a patient had paid 75 € for a first visit
    months earlier, and a fresh 19.020 € orthognathic schedule opened showing
    75 € already collected — a discount nobody gave.
    """
    from app.modules.budget.models import Budget

    def budget(number: str, total: str) -> Budget:
        return Budget(
            id=uuid4(),
            clinic_id=ctx["clinic_id"],
            patient_id=ctx["patient_id"],
            budget_number=number,
            status="draft",
            valid_from=date.today(),
            valid_until=date.today() + timedelta(days=30),
            subtotal=Decimal(total),
            total=Decimal(total),
            created_by=ctx["user_id"],
        )

    mine, other = budget("B-1", "1000.00"), budget("B-2", "75.00")
    db_session.add_all([mine, other])
    await db_session.commit()

    # 75 € collected long ago, against the other budget.
    payment = Payment(
        id=uuid4(),
        clinic_id=ctx["clinic_id"],
        patient_id=ctx["patient_id"],
        amount=Decimal("75.00"),
        currency="EUR",
        method="card",
        payment_date=date.today(),
        recorded_by=ctx["user_id"],
    )
    db_session.add(payment)
    await db_session.flush()
    db_session.add(
        PaymentAllocation(
            id=uuid4(),
            clinic_id=ctx["clinic_id"],
            payment_id=payment.id,
            target_type="budget",
            budget_id=other.id,
            amount=Decimal("75.00"),
            created_by=ctx["user_id"],
        )
    )
    await db_session.commit()

    r = await client.post(
        f"{BASE}/schedules",
        headers=auth_headers,
        json={
            "patient_id": str(ctx["patient_id"]),
            "budget_id": str(mine.id),
            "instalments": [{"label": "Anticipo", "amount": "1000.00"}],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["collected"] == "0"
    assert r.json()["data"]["instalments"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_a_schedule_without_a_budget_uses_the_whole_account(
    client, auth_headers, ctx, db_session
):
    """Nothing narrower to go on: it is the patient's whole account."""
    await _pay(db_session, ctx, "300.00")
    r = await _create(client, auth_headers, ctx, [{"label": "Único", "amount": "500.00"}])
    assert r.json()["data"]["collected"] == "300.00"


# ---------------------------------------------------------------------------
# Renegotiating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_schedule_can_be_renegotiated_in_place(client, auth_headers, ctx):
    r = await _create(
        client,
        auth_headers,
        ctx,
        [{"label": "Único", "amount": "1000.00"}],
    )
    schedule_id = r.json()["data"]["id"]

    updated = await client.put(
        f"{BASE}/schedules/{schedule_id}",
        headers=auth_headers,
        json={
            "instalments": [
                {"label": "Anticipo", "amount": "400.00"},
                {"label": "Resto", "due_date": "2099-01-01", "amount": "600.00"},
            ]
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()["data"]
    assert [i["label"] for i in body["instalments"]] == ["Anticipo", "Resto"]
    assert body["total"] == "1000.00"

    # The response is the line-up that was just written, not the previous one.
    fetched = (await client.get(f"{BASE}/schedules/{schedule_id}", headers=auth_headers)).json()[
        "data"
    ]
    assert len(fetched["instalments"]) == 2


@pytest.mark.asyncio
async def test_renegotiating_after_a_payment_recovers_the_money(
    client, auth_headers, ctx, db_session
):
    """The reason to touch a schedule is usually that the patient cannot pay.

    Settlement is derived, so the money already collected simply re-covers the
    new instalments in order — nothing is lost or double-counted.
    """
    r = await _create(
        client,
        auth_headers,
        ctx,
        [{"label": "A", "amount": "500.00"}, {"label": "B", "amount": "500.00"}],
    )
    schedule_id = r.json()["data"]["id"]
    await _pay(db_session, ctx, "500.00")

    updated = await client.put(
        f"{BASE}/schedules/{schedule_id}",
        headers=auth_headers,
        json={
            "instalments": [
                {"label": "A", "amount": "500.00"},
                {"label": "B1", "amount": "250.00"},
                {"label": "B2", "amount": "250.00"},
            ]
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()["data"]
    assert body["collected"] == "500.00"
    assert [i["status"] for i in body["instalments"]] == ["paid", "pending", "pending"]


@pytest.mark.asyncio
async def test_renegotiating_below_what_was_paid_reports_the_surplus(
    client, auth_headers, ctx, db_session
):
    r = await _create(client, auth_headers, ctx, [{"label": "Único", "amount": "500.00"}])
    schedule_id = r.json()["data"]["id"]
    await _pay(db_session, ctx, "500.00")

    updated = await client.put(
        f"{BASE}/schedules/{schedule_id}",
        headers=auth_headers,
        json={"instalments": [{"label": "Rebajado", "amount": "300.00"}]},
    )
    body = updated.json()["data"]
    assert body["pending"] == "0.00"
    # The 200 the patient overpaid is surfaced, not swallowed.
    assert body["unapplied"] == "200.00"


@pytest.mark.asyncio
async def test_an_empty_line_up_is_refused(client, auth_headers, ctx):
    r = await _create(client, auth_headers, ctx, [{"label": "Único", "amount": "500.00"}])
    schedule_id = r.json()["data"]["id"]

    updated = await client.put(
        f"{BASE}/schedules/{schedule_id}",
        headers=auth_headers,
        json={"instalments": []},
    )
    # 422 is this module's mapping for a ValueError from the service layer.
    assert updated.status_code == 422
    definition = ERROR_CATALOG["payments.schedule.instalment_required"]
    assert updated.json()["code"] == definition.code
    assert updated.json()["category"] == definition.category.value
    assert updated.json()["reference"] == updated.headers["x-request-id"]


@pytest.mark.asyncio
async def test_omitting_instalments_leaves_them_alone(client, auth_headers, ctx):
    """Full replace when present, untouched when absent."""
    r = await _create(
        client,
        auth_headers,
        ctx,
        [{"label": "A", "amount": "500.00"}, {"label": "B", "amount": "500.00"}],
    )
    schedule_id = r.json()["data"]["id"]

    updated = await client.put(
        f"{BASE}/schedules/{schedule_id}",
        headers=auth_headers,
        json={"notes": "Renegociado por teléfono"},
    )
    assert updated.status_code == 200, updated.text
    assert len(updated.json()["data"]["instalments"]) == 2
    assert updated.json()["data"]["notes"] == "Renegociado por teléfono"
