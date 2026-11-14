"""Memberships: plans, fees as payments, and what a member pays.

The expensive cases are the money ones: a fee is a payment of the patient
that must not read as credit nor cut what they owe for treatments, and an
included service performed must be booked at nothing, once per treatment,
and given back when the treatment is reopened.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.catalog.models import TreatmentCatalogItem, TreatmentCategory
from app.modules.memberships.models import MembershipBenefitUsage, MembershipPeriod
from app.modules.memberships.service import GRACE_DAYS, cycle_start, period_end
from app.modules.patients.models import Patient
from app.modules.payments.events import on_session_completed, on_session_reopened
from app.modules.payments.models import PatientEarnedEntry, PaymentAllocation
from app.modules.payments.service import PaymentReadService

BASE = "/api/v1/memberships"
TODAY = datetime.now(UTC).date()


@pytest.fixture
async def ctx(db_session: AsyncSession, test_clinic: Clinic) -> dict:
    category = TreatmentCategory(
        clinic_id=test_clinic.id, key="mem", names={"es": "M"}, is_system=True
    )
    db_session.add(category)
    await db_session.flush()
    cleaning, implant = (
        TreatmentCatalogItem(
            clinic_id=test_clinic.id,
            category_id=category.id,
            internal_code=code,
            names={"es": name},
            pricing_strategy="flat",
            treatment_scope="global_mouth",
            default_price=Decimal(price),
        )
        for code, name, price in (("LIMP", "Limpieza", "800"), ("IMPL", "Implante", "20000"))
    )
    patient = Patient(id=uuid4(), clinic_id=test_clinic.id, first_name="Mia", last_name="Socia")
    # An optional module of the Patients App: off until switched on.
    test_clinic.modules = ["memberships"]
    db_session.add_all([cleaning, implant, patient])
    await db_session.commit()
    return {
        "clinic": test_clinic,
        "patient_id": patient.id,
        "cleaning": cleaning.id,
        "implant": implant.id,
    }


def _plan_body(ctx: dict, **over) -> dict:
    body = {
        "name": "Plan Sonrisa",
        "fee": "500.00",
        "period": "monthly",
        "general_discount_percent": "10",
        "benefits": [
            {"catalog_item_id": str(ctx["cleaning"]), "kind": "included", "quantity": 2},
            {"catalog_item_id": str(ctx["implant"]), "kind": "discount", "discount_percent": "20"},
        ],
    }
    body.update(over)
    return body


async def _plan(client: AsyncClient, headers: dict, ctx: dict, **over) -> dict:
    response = await client.post(f"{BASE}/plans", json=_plan_body(ctx, **over), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _enroll(
    client: AsyncClient, headers: dict, ctx: dict, plan_id: str, starts_on: date = TODAY
) -> dict:
    response = await client.post(
        f"{BASE}/patients/{ctx['patient_id']}",
        json={
            "plan_id": plan_id,
            "starts_on": starts_on.isoformat(),
            "payment": {"method": "cash", "payment_date": starts_on.isoformat()},
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _session(ctx: dict, treatment_id: UUID, catalog_item_id: UUID, amount: str) -> dict:
    return {
        "clinic_id": str(ctx["clinic"].id),
        "patient_id": str(ctx["patient_id"]),
        "treatment_id": str(treatment_id),
        "catalog_item_id": str(catalog_item_id),
        "session_id": str(uuid4()),
        "amount": amount,
        "occurred_at": datetime.now(UTC).isoformat(),
    }


async def _earned(db: AsyncSession, treatment_id: UUID) -> Decimal:
    rows = await db.execute(
        select(PatientEarnedEntry.amount).where(PatientEarnedEntry.treatment_id == treatment_id)
    )
    return sum(rows.scalars().all(), Decimal("0"))


# --- Dates ------------------------------------------------------------------


def test_a_period_covers_a_month_or_a_year_to_the_day_before() -> None:
    assert period_end(date(2026, 1, 31), "monthly") == date(2026, 2, 27)
    assert period_end(date(2026, 3, 15), "monthly") == date(2026, 4, 14)
    assert period_end(date(2026, 3, 15), "annual") == date(2027, 3, 14)


def test_included_services_count_per_membership_year() -> None:
    started = date(2026, 3, 15)
    assert cycle_start(started, date(2026, 12, 1)) == started
    assert cycle_start(started, date(2027, 3, 14)) == started
    assert cycle_start(started, date(2027, 3, 15)) == date(2027, 3, 15)


# --- Switched on per clinic (ADR 0066) --------------------------------------


async def test_a_clinic_starts_with_memberships_off(
    client: AsyncClient, auth_headers: dict, test_clinic: Clinic
) -> None:
    assert test_clinic.modules is None
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()["data"]
    assert not any(p.startswith("memberships.") for p in me["permissions"])
    assert (await client.get(f"{BASE}/plans", headers=auth_headers)).status_code == 404


# --- Plans ------------------------------------------------------------------


async def test_a_plan_keeps_its_benefits_named_from_the_catalogue(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)

    assert plan["period"] == "monthly" and Decimal(plan["fee"]) == Decimal("500")
    by_item = {b["catalog_item_id"]: b for b in plan["benefits"]}
    assert by_item[str(ctx["cleaning"])]["quantity"] == 2
    assert by_item[str(ctx["cleaning"])]["internal_code"] == "LIMP"
    assert Decimal(by_item[str(ctx["implant"])]["discount_percent"]) == Decimal("20")


async def test_a_treatment_appears_once_in_a_plan(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    body = _plan_body(ctx)
    body["benefits"].append(
        {"catalog_item_id": str(ctx["cleaning"]), "kind": "included", "quantity": 1}
    )
    response = await client.post(f"{BASE}/plans", json=body, headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["code"] == "memberships.benefit.duplicate"


async def test_a_benefit_names_a_treatment_of_the_clinic(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    body = _plan_body(
        ctx, benefits=[{"catalog_item_id": str(uuid4()), "kind": "included", "quantity": 1}]
    )
    response = await client.post(f"{BASE}/plans", json=body, headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["code"] == "memberships.treatment.not_found"


async def test_an_archived_plan_takes_no_new_members(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    await client.post(f"{BASE}/plans/{plan['id']}/archive", headers=auth_headers)

    listed = (await client.get(f"{BASE}/plans", headers=auth_headers)).json()["data"]
    response = await client.post(
        f"{BASE}/patients/{ctx['patient_id']}",
        json={
            "plan_id": plan["id"],
            "starts_on": TODAY.isoformat(),
            "payment": {"method": "cash", "payment_date": TODAY.isoformat()},
        },
        headers=auth_headers,
    )
    assert listed == []
    assert response.status_code == 409
    assert response.json()["code"] == "memberships.plan.archived"


# --- Enrolment and fees -----------------------------------------------------


async def test_the_first_fee_is_a_payment_that_leaves_the_debt_alone(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    membership = await _enroll(client, auth_headers, ctx, plan["id"])

    period = membership["periods"][0]
    assert membership["state"] == "active"
    assert period["starts_on"] == TODAY.isoformat()
    assert period["ends_on"] == period_end(TODAY, "monthly").isoformat()
    assert period["payment_id"] is not None

    allocation = await db_session.scalar(
        select(PaymentAllocation).where(PaymentAllocation.payment_id == UUID(period["payment_id"]))
    )
    assert allocation.target_type == "membership"
    assert str(allocation.membership_period_id) == period["id"]

    summary = (
        await PaymentReadService.summaries_by_patients(
            db_session, ctx["clinic"].id, [ctx["patient_id"]]
        )
    )[ctx["patient_id"]]
    assert summary.total_paid == Decimal("500.00")
    assert summary.debt == Decimal("0")
    assert summary.on_account_balance == Decimal("0")


async def test_a_patient_holds_one_active_membership(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    await _enroll(client, auth_headers, ctx, plan["id"])
    response = await client.post(
        f"{BASE}/patients/{ctx['patient_id']}",
        json={
            "plan_id": plan["id"],
            "starts_on": TODAY.isoformat(),
            "payment": {"method": "cash", "payment_date": TODAY.isoformat()},
        },
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "memberships.membership.exists"


async def test_a_renewal_follows_on_from_the_last_paid_day(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    membership = await _enroll(client, auth_headers, ctx, plan["id"])
    first_end = date.fromisoformat(membership["periods"][0]["ends_on"])

    renewed = await client.post(
        f"{BASE}/{membership['id']}/periods",
        json={"payment": {"method": "card", "payment_date": TODAY.isoformat()}},
        headers=auth_headers,
    )
    assert renewed.status_code == 201, renewed.text
    latest = renewed.json()["data"]["periods"][0]
    assert latest["starts_on"] == (first_end + timedelta(days=1)).isoformat()
    assert renewed.json()["data"]["paid_through"] == latest["ends_on"]


async def test_a_lapsed_membership_starts_again_on_the_day_paid(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    long_ago = TODAY - timedelta(days=120)
    membership = await _enroll(client, auth_headers, ctx, plan["id"], starts_on=long_ago)
    assert membership["state"] == "expired"

    renewed = await client.post(
        f"{BASE}/{membership['id']}/periods",
        json={"payment": {"method": "cash", "payment_date": TODAY.isoformat()}},
        headers=auth_headers,
    )
    data = renewed.json()["data"]
    assert data["periods"][0]["starts_on"] == TODAY.isoformat()
    assert data["state"] == "active"


async def test_benefits_last_a_few_days_past_the_paid_period(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    # Paid a month that ended GRACE_DAYS - 1 days ago: still in force.
    starts = TODAY - timedelta(days=40)
    while period_end(starts, "monthly") < TODAY - timedelta(days=GRACE_DAYS - 1):
        starts += timedelta(days=1)
    membership = await _enroll(client, auth_headers, ctx, plan["id"], starts_on=starts)
    assert date.fromisoformat(membership["paid_through"]) < TODAY
    assert membership["state"] == "active"


async def test_editing_a_plan_leaves_paid_periods_on_their_terms(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    membership = await _enroll(client, auth_headers, ctx, plan["id"])
    edited = await client.put(
        f"{BASE}/plans/{plan['id']}",
        json=_plan_body(ctx, name="Plan Sonrisa 2027", fee="900.00", benefits=[]),
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text

    again = (await client.get(f"{BASE}/patients/{ctx['patient_id']}", headers=auth_headers)).json()[
        "data"
    ]["membership"]
    assert again["periods"][0]["plan_name"] == "Plan Sonrisa"
    assert Decimal(again["periods"][0]["amount"]) == Decimal("500")
    assert [i["quantity"] for i in again["included"]] == [2]
    assert membership["id"] == again["id"]


async def test_a_cancelled_membership_keeps_its_paid_days_without_grace(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    membership = await _enroll(client, auth_headers, ctx, plan["id"])
    cancelled = (
        await client.post(f"{BASE}/{membership['id']}/cancel", headers=auth_headers)
    ).json()["data"]

    assert cancelled["status"] == "cancelled"
    assert cancelled["state"] == "active"  # paid through the end of the month
    assert cancelled["covered_until"] == cancelled["paid_through"]
    renew = await client.post(
        f"{BASE}/{membership['id']}/periods",
        json={"payment": {"method": "cash", "payment_date": TODAY.isoformat()}},
        headers=auth_headers,
    )
    assert renew.status_code == 409


async def test_a_fee_refunded_in_full_uncovers_its_period_and_the_ledger(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    membership = await _enroll(client, auth_headers, ctx, plan["id"])
    period = membership["periods"][0]

    refund = await client.post(
        f"/api/v1/payments/{period['payment_id']}/refunds",
        json={"amount": "500.00", "method": "cash", "reason_code": "other"},
        headers=auth_headers,
    )
    assert refund.status_code == 201, refund.text

    # The refund leaves the patient owing nothing and holding no credit.
    summary = (
        await PaymentReadService.summaries_by_patients(
            db_session, ctx["clinic"].id, [ctx["patient_id"]]
        )
    )[ctx["patient_id"]]
    assert summary.total_paid == Decimal("0")
    assert summary.debt == Decimal("0")
    assert await _earned(db_session, UUID(period["id"])) == Decimal("0")

    # The bus ran the memberships handler: the period no longer covers.
    db_session.expire_all()
    stored = await db_session.get(MembershipPeriod, UUID(period["id"]))
    assert stored.status == "refunded"
    after = (await client.get(f"{BASE}/patients/{ctx['patient_id']}", headers=auth_headers)).json()[
        "data"
    ]["membership"]
    assert after["state"] == "expired"


async def test_a_fee_cannot_be_reallocated(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    membership = await _enroll(client, auth_headers, ctx, plan["id"])
    payment_id = membership["periods"][0]["payment_id"]

    response = await client.post(
        f"/api/v1/payments/{payment_id}/reallocate",
        json={"allocations": [{"target_type": "on_account", "amount": "500.00"}]},
        headers=auth_headers,
    )
    assert response.status_code in (400, 422)


# --- What a member pays -----------------------------------------------------


async def test_a_new_budget_line_suggests_the_member_discount(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    await _enroll(client, auth_headers, ctx, plan["id"])

    response = await client.post(
        "/api/v1/budget/budgets",
        json={
            "patient_id": str(ctx["patient_id"]),
            "items": [
                {"catalog_item_id": str(ctx["cleaning"])},
                {"catalog_item_id": str(ctx["implant"])},
                {
                    "catalog_item_id": str(ctx["implant"]),
                    "discount_type": "percentage",
                    "discount_value": "5",
                },
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    items = response.json()["data"]["items"]
    discounts = [(Decimal(i["discount_value"] or 0), i["notes"]) for i in items]
    assert discounts[0] == (Decimal("100"), "Incluido en membresía Plan Sonrisa")
    assert discounts[1] == (Decimal("20"), "Membresía Plan Sonrisa")
    # A discount typed by hand is the clinic's word: left alone.
    assert discounts[2] == (Decimal("5"), None)


async def test_an_included_service_is_booked_at_nothing_once_per_treatment(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    await _enroll(client, auth_headers, ctx, plan["id"])

    first, second, third = uuid4(), uuid4(), uuid4()
    await on_session_completed(_session(ctx, first, ctx["cleaning"], "800.00"))
    # Another session of the same treatment: the same unit covers it.
    await on_session_completed(_session(ctx, first, ctx["cleaning"], "800.00"))
    await on_session_completed(_session(ctx, second, ctx["cleaning"], "800.00"))
    # Two a year: the third cleaning pays, at the plan's general 10 %.
    await on_session_completed(_session(ctx, third, ctx["cleaning"], "800.00"))

    assert await _earned(db_session, first) == Decimal("0")
    assert await _earned(db_session, second) == Decimal("0")
    assert await _earned(db_session, third) == Decimal("720.00")
    usages = (await db_session.execute(select(MembershipBenefitUsage))).scalars().all()
    assert {u.treatment_id for u in usages} == {first, second}

    tab = (await client.get(f"{BASE}/patients/{ctx['patient_id']}", headers=auth_headers)).json()[
        "data"
    ]["membership"]
    assert [(i["quantity"], i["used"]) for i in tab["included"]] == [(2, 2)]


async def test_a_discounted_treatment_is_booked_at_the_member_price(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    await _enroll(client, auth_headers, ctx, plan["id"])
    treatment = uuid4()
    await on_session_completed(_session(ctx, treatment, ctx["implant"], "20000.00"))
    assert await _earned(db_session, treatment) == Decimal("16000.00")


async def test_reopening_gives_the_included_unit_back(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    await _enroll(client, auth_headers, ctx, plan["id"])
    treatment = uuid4()
    payload = _session(ctx, treatment, ctx["cleaning"], "800.00")
    await on_session_completed(payload)

    await on_session_reopened(payload)

    assert (await db_session.execute(select(MembershipBenefitUsage))).scalars().all() == []


async def test_without_a_membership_the_price_stands(db_session: AsyncSession, ctx: dict) -> None:
    treatment = uuid4()
    await on_session_completed(_session(ctx, treatment, ctx["cleaning"], "800.00"))
    assert await _earned(db_session, treatment) == Decimal("800.00")


async def test_switched_off_the_price_stands_and_nothing_is_lost(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    plan = await _plan(client, auth_headers, ctx)
    await _enroll(client, auth_headers, ctx, plan["id"])
    ctx["clinic"].modules = []
    await db_session.commit()

    treatment = uuid4()
    await on_session_completed(_session(ctx, treatment, ctx["cleaning"], "800.00"))

    assert await _earned(db_session, treatment) == Decimal("800.00")
    assert (await client.get(f"{BASE}/plans", headers=auth_headers)).status_code == 404
    ctx["clinic"].modules = ["memberships"]
    await db_session.commit()
    plans = (await client.get(f"{BASE}/plans", headers=auth_headers)).json()["data"]
    assert [p["id"] for p in plans] == [plan["id"]]
