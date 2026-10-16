"""Budgets that price a treatment plan.

Everything that writes a budget because of a plan lives here, on the
budget's side (ADR 0042). A plan never calls in: it announces that it
was confirmed, reopened or deleted, and the handlers below react in
their own transaction. The two operations a person asks for by name —
"generate the budget", "price what was added" — are budget endpoints
that read the plan through the ``PlanQuotes`` contract.

Whatever is created is announced with ``budget.created_for_plan``;
``treatment_plan`` links and logs it. This module never touches a
plan's row.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import PlanQuotes, provider
from app.core.events import EventType, event_bus
from app.database import async_session_maker

from .integrations import catalog_available, patients_available
from .models import Budget
from .providers import plan_budgets
from .service import BudgetItemService, BudgetService
from .workflow import BudgetWorkflowService

logger = logging.getLogger(__name__)

PLANS_UNAVAILABLE = "Treatment plans are not available"


def _announce(
    db: AsyncSession,
    clinic_id: UUID,
    plan_id: UUID | str,
    budget: Budget,
    kind: str,
    item_count: int,
    user_id: UUID | str | None,
) -> None:
    event_bus.publish_after_commit(
        db,
        EventType.BUDGET_CREATED_FOR_PLAN,
        {
            "clinic_id": str(clinic_id),
            "plan_id": str(plan_id),
            "budget_id": str(budget.id),
            "budget_number": budget.budget_number,
            "kind": kind,
            "item_count": item_count,
            "user_id": str(user_id) if user_id else None,
        },
    )


async def _plan_snapshot(db: AsyncSession, clinic_id: UUID, plan_id: UUID) -> dict:
    quotes = provider(PlanQuotes)
    if quotes is None:
        raise ValueError(PLANS_UNAVAILABLE)
    snapshot = await quotes.snapshot(db, clinic_id, plan_id)
    if snapshot is None:
        raise ValueError("Plan not found")
    return snapshot


async def _live_budget(db: AsyncSession, clinic_id: UUID, budget_id: str | None) -> Budget | None:
    if not budget_id:
        return None
    budget = await db.get(Budget, UUID(str(budget_id)))
    if budget is None or budget.clinic_id != clinic_id:
        return None
    if budget.status == "cancelled" or budget.deleted_at is not None:
        return None
    return budget


async def generate_for_plan(
    db: AsyncSession, clinic_id: UUID, plan_id: UUID, user_id: UUID
) -> Budget:
    """Mint the plan's own budget, for a plan that has none.

    The road for a plan confirmed while Budgets was off, or one whose
    confirmation never produced a budget.
    """
    snapshot = await _plan_snapshot(db, clinic_id, plan_id)
    if await _live_budget(db, clinic_id, snapshot.get("budget_id")) is not None:
        raise ValueError("Plan already has a budget linked")
    if not any(i.get("catalog_item_id") and i.get("treatment_id") for i in snapshot["items"]):
        raise ValueError("No catalog items found in plan to create budget")

    snapshot["budget_id"] = None
    budget = await BudgetService.create_from_plan_snapshot(db, clinic_id, user_id, snapshot)
    _announce(db, clinic_id, plan_id, budget, "primary", len(snapshot["items"]), user_id)
    return budget


async def price_additions(
    db: AsyncSession, clinic_id: UUID, plan_id: UUID, user_id: UUID
) -> tuple[Budget, bool, int]:
    """Put a price on the treatments added since the plan was confirmed.

    Normally this mints an **addendum**: its own draft, its own
    acceptance, carrying the plan's number so every query that walks a
    plan's budgets finds it. The document the patient was shown is not
    touched.

    It only has work to do because ``_on_treatment_added_to_plan`` stops
    at a budget that is not a draft. While the budget is still a draft
    that handler mirrors every addition as it happens, so the draft
    branch below is a **repair path**: a handler that raised is recorded
    and never retried (ADR 0020), and without it those lines could only
    be priced by hand.

    Returns ``(budget, created, item_count)``.
    """
    snapshot = await _plan_snapshot(db, clinic_id, plan_id)
    if snapshot.get("plan_status") not in ("pending", "active"):
        raise ValueError("Only a plan in progress can have an addendum")

    linked_id = snapshot.get("budget_id")
    priced = await plan_budgets.priced_treatment_ids(
        db, clinic_id, snapshot.get("plan_number"), UUID(linked_id) if linked_id else None
    )
    lines = [
        line
        for line in snapshot["items"]
        if line.get("treatment_id") and UUID(line["treatment_id"]) not in priced
    ]
    if not lines:
        raise ValueError("Every treatment in this plan is already budgeted")
    snapshot["items"] = lines

    current = await _live_budget(db, clinic_id, linked_id)
    if current is not None and current.status == "draft":
        for line in lines:
            if not line.get("catalog_item_id"):
                continue
            unit_price = line.get("unit_price")
            await BudgetItemService.create_item(
                db,
                clinic_id,
                current.id,
                {
                    "catalog_item_id": UUID(line["catalog_item_id"]),
                    "quantity": 1,
                    "treatment_id": UUID(line["treatment_id"]),
                    "tooth_number": line.get("tooth_number"),
                    "surfaces": line.get("surfaces"),
                    "unit_price": Decimal(unit_price) if unit_price is not None else None,
                },
            )
        await BudgetService._recalculate_totals(db, current)
        budget, created = current, False
    else:
        budget = await BudgetService.create_addendum_for_plan(db, clinic_id, user_id, snapshot)
        created = True

    _announce(
        db, clinic_id, plan_id, budget, "addendum" if created else "extended", len(lines), user_id
    )
    return budget, created, len(lines)


# --- Reactions to what a plan announces ------------------------------------


async def on_plan_confirmed(data: dict[str, Any]) -> None:
    """Mint the draft budget of a plan that was just confirmed.

    Repeatable: a plan whose linked budget is still live gets nothing
    new (``create_from_plan_snapshot`` hands that one back).
    """
    clinic_id, plan_id = data.get("clinic_id"), data.get("plan_id")
    user_id = data.get("confirmed_by_user_id")
    if not clinic_id or not plan_id or not user_id:
        return
    if not (patients_available() and catalog_available()):
        # No budget without them; "generate the budget" mints it once
        # they are back (``generate_for_plan``).
        logger.info("Plan %s confirmed while Patients or the catalog is off", plan_id)
        return

    async with async_session_maker() as db:
        budget = await BudgetService.create_from_plan_snapshot(
            db, UUID(clinic_id), UUID(user_id), data
        )
        if budget is None or str(budget.id) == str(data.get("budget_id")):
            await db.rollback()
            return
        _announce(
            db, UUID(clinic_id), plan_id, budget, "primary", len(data.get("items") or []), user_id
        )
        await db.commit()


async def on_plan_status_changed(data: dict[str, Any]) -> None:
    """Cancel the plan's budget when the plan goes back to draft.

    A reopened plan is being edited; the document that priced the old
    version is no longer an offer.
    """
    if data.get("new_status") != "draft" or data.get("old_status") not in ("pending", "active"):
        return
    clinic_id, user_id = data.get("clinic_id"), data.get("user_id")
    if not clinic_id or not user_id:
        return

    async with async_session_maker() as db:
        budget = await _live_budget(db, UUID(clinic_id), data.get("budget_id"))
        if budget is None or not BudgetWorkflowService.can_transition(budget.status, "cancelled"):
            return
        await BudgetWorkflowService.cancel_budget(
            db, budget, UUID(user_id), reason="Plan reopened for editing"
        )
        await db.commit()


async def on_plan_deleted(data: dict[str, Any]) -> None:
    """The budgets go with their plan, every version of them."""
    clinic_id, user_id = data.get("clinic_id"), data.get("deleted_by_user_id")
    plan_number = data.get("plan_number")
    if not clinic_id or not user_id or not plan_number:
        return
    budget_id = data.get("budget_id")

    async with async_session_maker() as db:
        await BudgetService.delete_for_plan(
            db, UUID(clinic_id), plan_number, UUID(budget_id) if budget_id else None, UUID(user_id)
        )
        await db.commit()
