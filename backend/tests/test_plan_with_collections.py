"""A plan the patient has paid into can only be closed.

Deleting it would take its budgets with it, and cancelling it
(`cancelled_by_clinic`) says the clinic called the work off. Both are
refused with 409 `PLAN_HAS_COLLECTIONS`; closing for any other reason still
works.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.treatment_plan.errors import ERROR_CATALOG
from tests.test_treatment_plan import (
    _create_plan_with_items,
    _ensure_clinic_and_patient,
    _seed_catalog_crown,
)

PLANS = "/api/v1/treatment_plan/treatment-plans"
PAYMENTS = "/api/v1/payments"
CODE = "PLAN_HAS_COLLECTIONS"


@pytest.fixture
async def setup(db_session: AsyncSession, auth_headers: dict, client: AsyncClient) -> dict:
    ctx = await _ensure_clinic_and_patient(db_session, client, auth_headers)
    ctx["crown_id"] = await _seed_catalog_crown(db_session, ctx["clinic_id"])
    return ctx


async def _confirmed_plan(client: AsyncClient, auth_headers: dict, setup: dict, tooth: int = 16):
    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [tooth])
    r = await client.post(f"{PLANS}/{plan_id}/confirm", headers=auth_headers)
    assert r.status_code == 200, r.text
    # The budget is minted by `budget` when it hears of the confirmation
    # (ADR 0042), so it is on the plan, not in the confirm response.
    r = await client.get(f"{PLANS}/{plan_id}", headers=auth_headers)
    return plan_id, r.json()["data"]["budget_id"], item_ids


async def _pay(client: AsyncClient, auth_headers: dict, setup: dict, allocation: dict) -> str:
    r = await client.post(
        PAYMENTS,
        headers=auth_headers,
        json={
            "patient_id": setup["patient_id"],
            "amount": allocation["amount"],
            "method": "cash",
            "allocations": [allocation],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


async def _cancel(
    client: AsyncClient, auth_headers: dict, plan_id: str, reason: str = "cancelled_by_clinic"
):
    return await client.post(
        f"{PLANS}/{plan_id}/close", headers=auth_headers, json={"closure_reason": reason}
    )


async def _status(client: AsyncClient, auth_headers: dict, plan_id: str) -> str:
    r = await client.get(f"{PLANS}/{plan_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]["status"]


@pytest.mark.asyncio
async def test_a_paid_plan_cannot_be_deleted(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_id, budget_id, _ = await _confirmed_plan(client, auth_headers, setup)
    await _pay(
        client,
        auth_headers,
        setup,
        {"target_type": "budget", "target_id": budget_id, "amount": "100.00"},
    )

    r = await client.delete(f"{PLANS}/{plan_id}", headers=auth_headers)
    assert r.status_code == 409, r.text
    assert r.json()["message"] == CODE
    definition = ERROR_CATALOG["treatment_plan.plan.has_collections"]
    assert r.json()["code"] == definition.code
    assert r.json()["category"] == definition.category.value
    assert r.json()["reference"] == r.headers["x-request-id"]

    # Nothing moved: the plan and its budget are both still there.
    assert await _status(client, auth_headers, plan_id) == "pending"
    r = await client.get(f"/api/v1/budget/budgets/{budget_id}", headers=auth_headers)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_a_paid_plan_cannot_be_cancelled(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_id, budget_id, _ = await _confirmed_plan(client, auth_headers, setup)
    await _pay(
        client,
        auth_headers,
        setup,
        {"target_type": "budget", "target_id": budget_id, "amount": "100.00"},
    )

    r = await _cancel(client, auth_headers, plan_id)
    assert r.status_code == 409, r.text
    assert r.json()["message"] == CODE
    assert await _status(client, auth_headers, plan_id) == "pending"


@pytest.mark.asyncio
async def test_a_paid_plan_can_still_be_closed(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """Closing is the way out the error message points to."""
    plan_id, budget_id, _ = await _confirmed_plan(client, auth_headers, setup)
    await _pay(
        client,
        auth_headers,
        setup,
        {"target_type": "budget", "target_id": budget_id, "amount": "100.00"},
    )

    r = await _cancel(client, auth_headers, plan_id, reason="patient_abandoned")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "closed"


@pytest.mark.asyncio
async def test_an_unpaid_plan_can_be_cancelled(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_id, _, _ = await _confirmed_plan(client, auth_headers, setup)

    r = await _cancel(client, auth_headers, plan_id)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "closed"


@pytest.mark.asyncio
async def test_a_fully_refunded_payment_does_not_count(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_id, budget_id, _ = await _confirmed_plan(client, auth_headers, setup)
    payment_id = await _pay(
        client,
        auth_headers,
        setup,
        {"target_type": "budget", "target_id": budget_id, "amount": "100.00"},
    )
    r = await client.post(
        f"{PAYMENTS}/{payment_id}/refunds",
        headers=auth_headers,
        json={"amount": "100.00", "method": "cash", "reason_code": "treatment_cancelled"},
    )
    assert r.status_code == 201, r.text

    r = await client.delete(f"{PLANS}/{plan_id}", headers=auth_headers)
    assert r.status_code == 204, r.text


@pytest.mark.asyncio
async def test_money_on_account_covering_the_plans_work_counts(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """A payment left on account still settles the plan's treatments."""
    # Two treatments, so finishing one leaves the plan open to be cancelled.
    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16, 15])
    r = await client.post(f"{PLANS}/{plan_id}/confirm", headers=auth_headers)
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"{PLANS}/{plan_id}/items/{item_ids[0]}/complete", headers=auth_headers, json={}
    )
    assert r.status_code == 200, r.text
    await _pay(client, auth_headers, setup, {"target_type": "on_account", "amount": "100.00"})

    r = await _cancel(client, auth_headers, plan_id)
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_money_on_another_plan_does_not_block_this_one(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    paid_plan, paid_budget, _ = await _confirmed_plan(client, auth_headers, setup, tooth=16)
    other_plan, _, _ = await _confirmed_plan(client, auth_headers, setup, tooth=15)
    await _pay(
        client,
        auth_headers,
        setup,
        {"target_type": "budget", "target_id": paid_budget, "amount": "100.00"},
    )

    r = await client.delete(f"{PLANS}/{other_plan}", headers=auth_headers)
    assert r.status_code == 204, r.text
    r = await _cancel(client, auth_headers, paid_plan)
    assert r.status_code == 409, r.text
