"""What the clinic said it wanted this month, next to what it got.

A figure on its own says what happened; a figure next to a target says
whether that was good. The targets are the clinic's own, set by hand,
one row per month — not derived from history, because a goal copied from
last month is a description, not a decision.

The actuals come from the same places the panel reads: collection and
production through the `CollectionReport` contract (ADR 0039, so this
module still imports nothing of `payments`), first visits from the
scheduling service. Nothing is recomputed here.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.contracts import CollectionReport, provider

from .integrations import running
from .models import MonthlyTarget
from .services import SchedulingReportService


def month_bounds(month: date) -> tuple[date, date]:
    """The first and last day of ``month``'s month."""
    first = month.replace(day=1)
    return first, first.replace(day=monthrange(first.year, first.month)[1])


@dataclass(frozen=True, slots=True)
class Attainment:
    """One goal: what was asked, what arrived, and how far that is.

    ``ratio`` is ``None`` when no target was set — "no goal" and "goal of
    zero" are different answers and a screen must not draw them alike.
    """

    target: Decimal | None
    actual: Decimal
    ratio: float | None

    @staticmethod
    def of(target: Decimal | None, actual: Decimal) -> Attainment:
        if target is None or target <= 0:
            return Attainment(target=target, actual=actual, ratio=None)
        return Attainment(
            target=target, actual=actual, ratio=round(float(actual / target) * 100, 1)
        )


async def get_or_create(db: AsyncSession, clinic_id: UUID, month: date) -> MonthlyTarget:
    first, _ = month_bounds(month)
    row = await db.get(MonthlyTarget, (clinic_id, first))
    if row is None:
        row = MonthlyTarget(clinic_id=clinic_id, month=first)
        db.add(row)
        await db.flush()
    return row


async def set_targets(
    db: AsyncSession,
    clinic_id: UUID,
    month: date,
    *,
    collected: Decimal | None,
    production: Decimal | None,
    new_patients: int | None,
) -> MonthlyTarget:
    row = await get_or_create(db, clinic_id, month)
    row.collected_target = collected
    row.production_target = production
    row.new_patients_target = new_patients
    await db.flush()
    return row


async def progress(
    db: AsyncSession, clinic: Clinic, month: date
) -> tuple[MonthlyTarget, dict[str, Attainment]]:
    """The month's targets and how the clinic is doing against them.

    A goal whose App is switched off reports an actual of zero rather
    than disappearing: the clinic set it, and silently dropping it would
    read as "nothing happened" instead of "we cannot see".
    """
    row = await get_or_create(db, clinic.id, month)
    first, last = month_bounds(month)

    collected = Decimal("0")
    production = Decimal("0")
    report = provider(CollectionReport)
    if report is not None:
        period = await report.collected_in_period(
            db, clinic.id, clinic.currency, clinic.timezone, first, last
        )
        collected = period.net_collected
        produced = await report.produced_by_professional(
            db, clinic.id, clinic.timezone, first, last
        )
        production = sum((row_.total for row_ in produced), Decimal("0"))

    new_patients = 0
    if running("agenda"):
        visits = await SchedulingReportService.get_first_visits(db, clinic.id, first, last)
        new_patients = visits["new_patients"]

    return row, {
        "collected": Attainment.of(row.collected_target, collected),
        "production": Attainment.of(row.production_target, production),
        "new_patients": Attainment.of(
            Decimal(row.new_patients_target) if row.new_patients_target is not None else None,
            Decimal(new_patients),
        ),
    }


async def months_with_targets(db: AsyncSession, clinic_id: UUID, limit: int = 12) -> list[date]:
    """The months this clinic has set goals for, newest first."""
    rows = (
        await db.execute(
            select(MonthlyTarget.month)
            .where(MonthlyTarget.clinic_id == clinic_id)
            .order_by(MonthlyTarget.month.desc())
            .limit(limit)
        )
    ).scalars()
    return list(rows)
