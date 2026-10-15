"""Cashbox services.

Phase 1 owns one thing: the money that enters and leaves the till without
being a patient payment. The arqueo that consumes it arrives in phase 2;
nothing here needs to change when it does, because closing a day only
stamps `closing_id` on rows this service already writes.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.utils.clinic_time import clinic_date, clinic_day_window
from app.modules.payments.models import Payment, Refund

from .models import CashClosing, CashMovement, LateEntryAck
from .schemas import (
    CashClosingResponse,
    CashMovementDayTotals,
    CashPeriod,
    CashPosition,
    LateEntry,
    MethodTotal,
    UserBrief,
)


class CashboxError(ValueError):
    """A refusal the caller can fix. Routers turn it into a 422."""


class MovementService:
    """CRUD for till movements, with one rule that matters.

    **A movement stops being editable the moment its day is closed.** Until
    then it is a note someone left and correcting it costs nothing; after,
    it is part of an accounting record that a person counted and signed
    off, and silently changing it would make that record a lie. The rule
    lives here rather than in the router so the agent tools inherit it.
    """

    @staticmethod
    async def list(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        direction: str | None = None,
        category: str | None = None,
    ) -> list[CashMovement]:
        filters = [CashMovement.clinic_id == clinic_id]
        if date_from is not None:
            filters.append(CashMovement.business_date >= date_from)
        if date_to is not None:
            filters.append(CashMovement.business_date <= date_to)
        if direction:
            filters.append(CashMovement.direction == direction)
        if category:
            filters.append(CashMovement.category == category)

        result = await db.execute(
            select(CashMovement)
            .options(joinedload(CashMovement.recorder))
            .where(*filters)
            # Newest first within a day: the till screen is used while the
            # day is still running, and the row you just typed is the one
            # you check.
            .order_by(CashMovement.business_date.desc(), CashMovement.created_at.desc())
        )
        return list(result.unique().scalars().all())

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, movement_id: UUID) -> CashMovement | None:
        result = await db.execute(
            select(CashMovement)
            .options(joinedload(CashMovement.recorder))
            .where(
                CashMovement.id == movement_id,
                CashMovement.clinic_id == clinic_id,
            )
        )
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession,
        clinic_id: UUID,
        currency: str,
        user_id: UUID,
        data: dict,
    ) -> CashMovement:
        movement = CashMovement(
            clinic_id=clinic_id,
            currency=currency,
            recorded_by=user_id,
            **data,
        )
        db.add(movement)
        # `id` is a Python-side `default=uuid7`, filled on flush and not
        # before; returning the row unflushed hands the response model an
        # id of None and Pydantic refuses it with a 500.
        await db.flush()
        return movement

    @staticmethod
    async def update(
        db: AsyncSession,
        clinic_id: UUID,
        movement_id: UUID,
        data: dict,
    ) -> CashMovement | None:
        movement = await MovementService.get(db, clinic_id, movement_id)
        if movement is None:
            return None
        MovementService._refuse_if_closed(movement)
        MovementService._refuse_if_payout(movement)
        for field, value in data.items():
            setattr(movement, field, value)
        await db.flush()
        return movement

    @staticmethod
    async def delete(db: AsyncSession, clinic_id: UUID, movement_id: UUID) -> bool:
        movement = await MovementService.get(db, clinic_id, movement_id)
        if movement is None:
            return False
        MovementService._refuse_if_closed(movement)
        MovementService._refuse_if_payout(movement)
        # Hard delete, deliberately. This is not patient data and an open
        # day has no accounting weight yet — a mistyped row the same
        # minute it was typed should leave nothing behind. Everything that
        # survives the close is immutable instead, which is the protection
        # that actually matters.
        await db.delete(movement)
        await db.flush()
        return True

    @staticmethod
    def _refuse_if_payout(movement: CashMovement) -> None:
        """A settlement payout is edited where it was created, not here.

        `liquidations` writes these and points a foreign key at them, so a
        delete from this side is refused by the database with an integrity
        error and a 500 — and an *edit* is worse, because it succeeds and
        leaves a settlement claiming it paid an amount the till never moved.

        The check reads the category rather than asking `liquidations`:
        this module knows nothing about that one and must not start to.
        """
        if movement.category == "professional_payout":
            raise CashboxError(
                "This movement is the payout of a settlement. Undo the payment "
                "from the settlement itself, which removes this row with it."
            )

    @staticmethod
    def _refuse_if_closed(movement: CashMovement) -> None:
        if movement.closing_id is not None:
            raise CashboxError(
                "This movement belongs to a closed day and can no longer be changed. "
                "Reopen the day first."
            )

    @staticmethod
    async def day_totals(
        db: AsyncSession,
        clinic_id: UUID,
        currency: str,
        business_date: date,
    ) -> CashMovementDayTotals:
        """What moved on one day, split by direction **and** by till.

        Split by direction rather than netted because the till's arithmetic
        uses the two halves separately, and because a day of 5.000 in and
        5.000 out is not the same story as a quiet day — a single net figure
        tells both as zero.

        Split by till because a movement no longer means a movement of cash.
        The lab paid by transfer belongs to the day's money and not to the
        drawer, so the two live side by side: `total_*` is what moved,
        `cash_*` is the drawer's share and the only part the arqueo may
        read. Conflating them would make the expected cash include money
        that was never in it, and every count would report a shortfall.
        """
        result = await db.execute(
            select(
                CashMovement.direction,
                CashMovement.method,
                func.coalesce(func.sum(CashMovement.amount), Decimal("0")),
                func.count(CashMovement.id),
            )
            .where(
                CashMovement.clinic_id == clinic_id,
                CashMovement.business_date == business_date,
            )
            .group_by(CashMovement.direction, CashMovement.method)
        )
        totals = {"in": Decimal("0"), "out": Decimal("0")}
        cash = {"in": Decimal("0"), "out": Decimal("0")}
        count = 0
        for direction, method, amount, rows in result.all():
            totals[direction] += amount
            if method == "cash":
                cash[direction] += amount
            count += rows
        return CashMovementDayTotals(
            business_date=business_date,
            currency=currency,
            total_in=totals["in"],
            total_out=totals["out"],
            cash_in=cash["in"],
            cash_out=cash["out"],
            net=totals["in"] - totals["out"],
            count=count,
        )


class ClosingService:
    """The arqueo: what the drawer should hold, and what it actually did.

    The expected figure is arithmetic over four sources, and the day
    boundary is different for two of them:

    - `Payment.payment_date` is already a DATE in the clinic's calendar, so
      it is compared directly. Nothing to convert.
    - `Refund.refunded_at` is a true instant and has to be resolved through
      the clinic's zone first. Comparing it against a bare date put a refund
      issued at 00:30 in Madrid on the previous day, which is the bug this
      helper exists to prevent.

    Only **cash** counts. A card batch settles itself against the terminal
    and a transfer reaches the bank on its own schedule; putting them in a
    drawer count is the commonest way this feature is made useless.
    """

    @staticmethod
    async def position(
        db: AsyncSession,
        clinic_id: UUID,
        currency: str,
        timezone: str,
        business_date: date,
    ) -> CashPosition:
        window_start, window_end = clinic_day_window(business_date, business_date, timezone)

        collected = await db.execute(
            select(
                Payment.method,
                func.coalesce(func.sum(Payment.amount), Decimal("0")),
                func.count(Payment.id),
            )
            .where(
                Payment.clinic_id == clinic_id,
                Payment.payment_date == business_date,
            )
            .group_by(Payment.method)
        )
        by_method = [
            MethodTotal(method=method, amount=amount, count=count)
            for method, amount, count in collected.all()
        ]
        cash_collected = next((m.amount for m in by_method if m.method == "cash"), Decimal("0"))

        # A refund's method can differ from its payment's: a card payment
        # handed back in notes still empties the drawer, and only the
        # refund's own method says whether it did.
        cash_refunded = await db.scalar(
            select(func.coalesce(func.sum(Refund.amount), Decimal("0"))).where(
                Refund.clinic_id == clinic_id,
                Refund.method == "cash",
                Refund.refunded_at >= window_start,
                Refund.refunded_at < window_end,
            )
        ) or Decimal("0")

        movements = await MovementService.day_totals(db, clinic_id, currency, business_date)
        closing = await ClosingService.standing(db, clinic_id, business_date)

        # A day already counted keeps the float it was counted against;
        # an open one inherits yesterday's, which is how the chain runs
        # itself instead of asking somebody to remember a number.
        opening_float = (
            closing.opening_float
            if closing is not None
            else await ClosingService.suggested_opening_float(db, clinic_id, business_date)
        )

        # `cash_*`, never `total_*`: a transfer belongs to the day's money
        # and not to the drawer, and counting it here would make every
        # arqueo report a shortfall the size of the clinic's bank payments.
        expected = (
            opening_float + cash_collected - cash_refunded + movements.cash_in - movements.cash_out
        )

        return CashPosition(
            business_date=business_date,
            currency=currency,
            opening_float=opening_float,
            cash_collected=cash_collected,
            cash_refunded=cash_refunded,
            movements_in=movements.cash_in,
            movements_out=movements.cash_out,
            expected_cash=expected,
            collected_by_method=by_method,
            closing=CashClosingResponse.model_validate(closing) if closing else None,
        )

    @staticmethod
    async def suggested_opening_float(
        db: AsyncSession, clinic_id: UUID, business_date: date
    ) -> Decimal:
        """Yesterday's closing float, or zero for a clinic's first count.

        Looks back at the most recent standing count *before* this day
        rather than literally the day before: clinics close on Sundays, and
        a Monday whose float reset to zero because Sunday was never counted
        would report a shortfall of the whole drawer.
        """
        previous = await db.scalar(
            select(CashClosing.closing_float)
            .where(
                CashClosing.clinic_id == clinic_id,
                CashClosing.status == "closed",
                CashClosing.business_date < business_date,
            )
            .order_by(desc(CashClosing.business_date))
            .limit(1)
        )
        return previous if previous is not None else Decimal("0")

    @staticmethod
    async def standing(
        db: AsyncSession, clinic_id: UUID, business_date: date
    ) -> CashClosing | None:
        """The count that currently stands for a day, if it has one."""
        result = await db.execute(
            select(CashClosing)
            .options(joinedload(CashClosing.closer), joinedload(CashClosing.reopener))
            .where(
                CashClosing.clinic_id == clinic_id,
                CashClosing.business_date == business_date,
                CashClosing.status == "closed",
            )
        )
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def list(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        include_superseded: bool = False,
    ) -> list[CashClosing]:
        filters = [CashClosing.clinic_id == clinic_id]
        if date_from is not None:
            filters.append(CashClosing.business_date >= date_from)
        if date_to is not None:
            filters.append(CashClosing.business_date <= date_to)
        if not include_superseded:
            filters.append(CashClosing.status == "closed")
        result = await db.execute(
            select(CashClosing)
            .options(joinedload(CashClosing.closer), joinedload(CashClosing.reopener))
            .where(*filters)
            .order_by(desc(CashClosing.business_date), desc(CashClosing.closed_at))
        )
        return list(result.unique().scalars().all())

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, closing_id: UUID) -> CashClosing | None:
        result = await db.execute(
            select(CashClosing)
            .options(joinedload(CashClosing.closer), joinedload(CashClosing.reopener))
            .where(CashClosing.id == closing_id, CashClosing.clinic_id == clinic_id)
            # `populate_existing` because this is the read that runs straight
            # after a write: without it the identity map hands back the
            # instance as it was, and a reopen answers with `reopener: null`
            # while the database holds the user who did it. Same trap
            # `PlanTemplateService.get` documents.
            .execution_options(populate_existing=True)
        )
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def close(
        db: AsyncSession,
        clinic_id: UUID,
        currency: str,
        timezone: str,
        user_id: UUID,
        data: dict,
    ) -> CashClosing:
        business_date: date = data["business_date"]

        # The clinic's today, not the server's: a container on UTC is
        # already on tomorrow while a clinic at UTC-6 is still working, and
        # refusing their own current day would be absurd.
        if business_date > clinic_date(datetime.now(UTC), timezone):
            raise CashboxError("A day in the future cannot be counted.")

        if await ClosingService.standing(db, clinic_id, business_date) is not None:
            raise CashboxError("This day is already counted. Reopen it before counting again.")

        position = await ClosingService.position(db, clinic_id, currency, timezone, business_date)
        # The opening float is the caller's: they are the one who knows
        # what was in the drawer this morning, and the suggestion is only a
        # suggestion. Everything that follows is recomputed against it, so
        # the stored figures are internally consistent whatever they chose.
        opening_float: Decimal = data["opening_float"]
        expected = (
            opening_float
            + position.cash_collected
            - position.cash_refunded
            + position.movements_in
            - position.movements_out
        )
        counted: Decimal = data["counted_cash"]
        difference = counted - expected

        notes = (data.get("notes") or "").strip() or None
        if difference != 0 and not notes:
            raise CashboxError(
                "The count does not match the expected cash. Say what happened "
                "before closing the day."
            )

        closing_float: Decimal = data["closing_float"]
        if closing_float > counted:
            raise CashboxError("More cash cannot be left for tomorrow than was counted today.")

        closing = CashClosing(
            clinic_id=clinic_id,
            business_date=business_date,
            status="closed",
            currency=currency,
            opening_float=opening_float,
            expected_cash=expected,
            counted_cash=counted,
            difference=difference,
            closing_float=closing_float,
            snapshot=_snapshot(position, opening_float, expected),
            notes=notes,
            closed_at=datetime.now(UTC),
            closed_by=user_id,
        )
        db.add(closing)
        await db.flush()

        # Stamping is what freezes the rows the count was made from. Done
        # after the flush so `closing.id` exists.
        #
        # Cash rows only, and that is the whole meaning of the stamp: a
        # closing is a statement about the drawer, so it freezes what was
        # in the drawer. Freezing the rent paid by transfer because someone
        # counted Tuesday's notes would make a typo in it uncorrectable for
        # a reason that has nothing to do with it.
        await db.execute(
            CashMovement.__table__.update()
            .where(
                CashMovement.clinic_id == clinic_id,
                CashMovement.business_date == business_date,
                CashMovement.method == "cash",
                CashMovement.closing_id.is_(None),
            )
            .values(closing_id=closing.id)
        )
        return closing

    @staticmethod
    async def reopen(
        db: AsyncSession,
        clinic_id: UUID,
        closing_id: UUID,
        user_id: UUID,
        reason: str,
    ) -> CashClosing | None:
        closing = await ClosingService.get(db, clinic_id, closing_id)
        if closing is None:
            return None
        if closing.status != "closed":
            raise CashboxError("This count has already been superseded.")

        closing.status = "reopened"
        closing.reopened_at = datetime.now(UTC)
        closing.reopened_by = user_id
        closing.reopen_reason = reason

        # The movements go back to being editable. Only the ones this count
        # stamped: a day counted twice has rows belonging to each attempt,
        # and releasing all of them would unfreeze a count still standing.
        await db.execute(
            CashMovement.__table__.update()
            .where(
                CashMovement.clinic_id == clinic_id,
                CashMovement.closing_id == closing.id,
            )
            .values(closing_id=None)
        )
        await db.flush()
        return closing


def _snapshot(position: CashPosition, opening_float: Decimal, expected: Decimal) -> dict:
    """The full breakdown, frozen.

    Stored as JSON rather than recomputed because a period view must read
    the day as it was counted. Recomputing would let a payment back-dated
    into a closed day quietly change a number somebody signed.

    `str()` on every Decimal: JSONB has no decimal type and float would
    lose cents on exactly the figures that must not lose them.
    """
    return {
        "opening_float": str(opening_float),
        "cash_collected": str(position.cash_collected),
        "cash_refunded": str(position.cash_refunded),
        "movements_in": str(position.movements_in),
        "movements_out": str(position.movements_out),
        "expected_cash": str(expected),
        "collected_by_method": [
            {"method": m.method, "amount": str(m.amount), "count": m.count}
            for m in position.collected_by_method
        ],
    }


# --- Period cuts ------------------------------------------------------


def period_bounds(kind: str, anchor: date) -> tuple[date, date]:
    """The inclusive first and last day of the period containing `anchor`.

    Pure, and separated from everything that touches a database because the
    calendar is where this gets subtly wrong and a unit test is the cheapest
    place to hold it.

    - **week**: Monday to Sunday, matching what `payments`' own `trends`
      already buckets by. A clinic that thinks of its week differently still
      reads the same seven days everywhere in the app.
    - **fortnight**: the **1st-15th and 16th-end of month**, not "every
      fourteen days". In Mexico the quincena is a calendar thing because it
      is when payroll is paid; a rolling fortnight drifts off the month by
      March and the report stops lining up with the only thing it is for.
    - **month**: the 1st to the last day, whatever length that is.
    """
    if kind == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if kind == "fortnight":
        if anchor.day <= 15:
            return anchor.replace(day=1), anchor.replace(day=15)
        last = monthrange(anchor.year, anchor.month)[1]
        return anchor.replace(day=16), anchor.replace(day=last)
    if kind == "month":
        last = monthrange(anchor.year, anchor.month)[1]
        return anchor.replace(day=1), anchor.replace(day=last)
    raise CashboxError(f"Unknown period kind: {kind}")


class PeriodService:
    """The weekly / fortnightly / monthly cut.

    Built **from the arqueos**, never recalculated from `payments`. The
    difference is the whole point of the phase: recomputed from payments, a
    fortnight with three uncounted days inside it looks immaculate;
    assembled from closings, it says which three days are missing.
    """

    @staticmethod
    async def summary(
        db: AsyncSession,
        clinic_id: UUID,
        currency: str,
        timezone: str,
        kind: str,
        anchor: date,
    ) -> CashPeriod:
        date_from, date_to = period_bounds(kind, anchor)

        closings = await ClosingService.list(db, clinic_id, date_from=date_from, date_to=date_to)

        totals = {
            "cash_collected": Decimal("0"),
            "cash_refunded": Decimal("0"),
            "movements_in": Decimal("0"),
            "movements_out": Decimal("0"),
        }
        difference_total = Decimal("0")
        days_off = 0
        by_method: dict[str, dict] = {}

        for closing in closings:
            snapshot = closing.snapshot or {}
            for key in totals:
                # `str()` in, `Decimal()` out: JSONB has no decimal type and
                # a float round-trip loses cents on exactly the figures that
                # must not lose them.
                totals[key] += Decimal(str(snapshot.get(key, "0")))
            difference_total += closing.difference
            if closing.difference != 0:
                days_off += 1
            for row in snapshot.get("collected_by_method", []):
                entry = by_method.setdefault(row["method"], {"amount": Decimal("0"), "count": 0})
                entry["amount"] += Decimal(str(row["amount"]))
                entry["count"] += int(row["count"])

        counted = {c.business_date for c in closings}
        pending = await PeriodService.pending_days(
            db, clinic_id, timezone, date_from, date_to, counted
        )

        return CashPeriod(
            kind=kind,
            date_from=date_from,
            date_to=date_to,
            currency=currency,
            counted_days=len(counted),
            pending_days=pending,
            cash_collected=totals["cash_collected"],
            cash_refunded=totals["cash_refunded"],
            movements_in=totals["movements_in"],
            movements_out=totals["movements_out"],
            difference_total=difference_total,
            days_off=days_off,
            collected_by_method=[
                MethodTotal(method=m, amount=v["amount"], count=v["count"])
                for m, v in sorted(by_method.items())
            ],
            closings=[CashClosingResponse.model_validate(c) for c in closings],
        )

    @staticmethod
    async def pending_days(
        db: AsyncSession,
        clinic_id: UUID,
        timezone: str,
        date_from: date,
        date_to: date,
        counted: set[date],
    ) -> list[date]:
        """Days money moved and nobody counted.

        Deliberately **not** "every calendar day without a closing". A
        clinic that shuts on Sunday would then be told it is four days
        behind every month, the warning would be wrong every time, and
        within a fortnight nobody would read it. A day qualifies only if
        something actually happened in the drawer: cash taken, cash handed
        back, or a movement recorded.
        """
        days: set[date] = set()

        paid = await db.execute(
            select(Payment.payment_date)
            .where(
                Payment.clinic_id == clinic_id,
                Payment.method == "cash",
                Payment.payment_date >= date_from,
                Payment.payment_date <= date_to,
            )
            .distinct()
        )
        days.update(row[0] for row in paid.all())

        moved = await db.execute(
            select(CashMovement.business_date)
            .where(
                CashMovement.clinic_id == clinic_id,
                CashMovement.business_date >= date_from,
                CashMovement.business_date <= date_to,
            )
            .distinct()
        )
        days.update(row[0] for row in moved.all())

        # Refunds are instants, so the day they belong to is resolved
        # through the clinic's zone rather than read off the timestamp —
        # the same asymmetry the arqueo's arithmetic lives with.
        window_start, window_end = clinic_day_window(date_from, date_to, timezone)
        refunded = await db.execute(
            select(Refund.refunded_at).where(
                Refund.clinic_id == clinic_id,
                Refund.method == "cash",
                Refund.refunded_at >= window_start,
                Refund.refunded_at < window_end,
            )
        )
        days.update(clinic_date(row[0], timezone) for row in refunded.all())

        return sorted(day for day in days if day not in counted)


# --- Entries that landed after their day was counted -------------------


class LateEntryService:
    """Money written down against a day that had already been counted.

    The situation is ordinary: reception records Friday's cash on Monday,
    and Friday was closed on Friday. Refusing the back-date would only make
    them file it under today and lie about the date, which is worse — so it
    is allowed, the signed count keeps its figures, and the entry surfaces
    here instead.

    What makes the three kinds late is not the same test in each case,
    which is why this is not one query:

    - a **payment** or a **refund** is late when it was *written* after the
      day was signed (`created_at > closing.closed_at`);
    - a **movement** is late when its day is closed and it still carries no
      `closing_id` — closing stamps every open row of the day, so a null
      one on a closed day can only have arrived afterwards.
    """

    @staticmethod
    async def list(
        db: AsyncSession,
        clinic_id: UUID,
        currency: str,
        timezone: str,
        date_from: date,
        date_to: date,
        *,
        include_acknowledged: bool = False,
    ) -> list[LateEntry]:
        closings = {
            c.business_date: c
            for c in await ClosingService.list(db, clinic_id, date_from=date_from, date_to=date_to)
        }
        if not closings:
            return []

        entries: list[LateEntry] = []

        payments = await db.execute(
            select(Payment).where(
                Payment.clinic_id == clinic_id,
                Payment.method == "cash",
                Payment.payment_date >= date_from,
                Payment.payment_date <= date_to,
            )
        )
        for payment in payments.scalars().all():
            closing = closings.get(payment.payment_date)
            if closing is None or payment.created_at <= closing.closed_at:
                continue
            entries.append(
                LateEntry(
                    kind="payment",
                    entry_id=payment.id,
                    business_date=payment.payment_date,
                    currency=payment.currency,
                    amount=payment.amount,
                    description=payment.reference,
                    recorded_at=payment.created_at,
                    closed_at=closing.closed_at,
                )
            )

        window_start, window_end = clinic_day_window(date_from, date_to, timezone)
        refunds = await db.execute(
            select(Refund).where(
                Refund.clinic_id == clinic_id,
                Refund.method == "cash",
                Refund.refunded_at >= window_start,
                Refund.refunded_at < window_end,
            )
        )
        for refund in refunds.scalars().all():
            day = clinic_date(refund.refunded_at, timezone)
            closing = closings.get(day)
            if closing is None or refund.created_at <= closing.closed_at:
                continue
            entries.append(
                LateEntry(
                    kind="refund",
                    entry_id=refund.id,
                    business_date=day,
                    currency=currency,
                    # Negative: a refund empties the drawer.
                    amount=-refund.amount,
                    description=refund.reason_code,
                    recorded_at=refund.created_at,
                    closed_at=closing.closed_at,
                )
            )

        # Cash rows only. A non-cash movement never carries a stamp — the
        # closing does not freeze what it did not count — so without this
        # filter every transfer in a closed day would be reported late, for
        # ever, and the list this screen exists to empty could never empty.
        movements = await db.execute(
            select(CashMovement).where(
                CashMovement.clinic_id == clinic_id,
                CashMovement.business_date >= date_from,
                CashMovement.business_date <= date_to,
                CashMovement.method == "cash",
                CashMovement.closing_id.is_(None),
            )
        )
        for movement in movements.scalars().all():
            closing = closings.get(movement.business_date)
            if closing is None:
                continue
            entries.append(
                LateEntry(
                    kind="movement",
                    entry_id=movement.id,
                    business_date=movement.business_date,
                    currency=movement.currency,
                    amount=(movement.amount if movement.direction == "in" else -movement.amount),
                    description=movement.concept,
                    recorded_at=movement.created_at,
                    closed_at=closing.closed_at,
                )
            )

        acks = await LateEntryService._acks(db, clinic_id, date_from, date_to)
        for entry in entries:
            ack = acks.get((entry.kind, entry.entry_id))
            if ack is None:
                continue
            entry.acknowledged = True
            entry.resolution = ack.resolution
            entry.acknowledged_at = ack.acknowledged_at
            entry.acknowledger = (
                UserBrief.model_validate(ack.acknowledger) if ack.acknowledger else None
            )

        if not include_acknowledged:
            entries = [e for e in entries if not e.acknowledged]

        # Newest day first, and within a day the order they were written —
        # which is the order somebody reconciling will read them in.
        entries.sort(key=lambda e: (e.business_date, e.recorded_at), reverse=True)
        return entries

    @staticmethod
    async def _acks(
        db: AsyncSession, clinic_id: UUID, date_from: date, date_to: date
    ) -> dict[tuple[str, UUID], LateEntryAck]:
        result = await db.execute(
            select(LateEntryAck)
            .options(joinedload(LateEntryAck.acknowledger))
            .where(
                LateEntryAck.clinic_id == clinic_id,
                LateEntryAck.business_date >= date_from,
                LateEntryAck.business_date <= date_to,
            )
        )
        return {(ack.entry_kind, ack.entry_id): ack for ack in result.unique().scalars().all()}

    @staticmethod
    async def acknowledge(
        db: AsyncSession,
        clinic_id: UUID,
        user_id: UUID,
        data: dict,
    ) -> LateEntryAck:
        existing = await db.execute(
            select(LateEntryAck).where(
                LateEntryAck.clinic_id == clinic_id,
                LateEntryAck.entry_kind == data["kind"],
                LateEntryAck.entry_id == data["entry_id"],
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise CashboxError("This entry has already been dealt with.")

        ack = LateEntryAck(
            clinic_id=clinic_id,
            entry_kind=data["kind"],
            entry_id=data["entry_id"],
            business_date=data["business_date"],
            resolution=data["resolution"],
            acknowledged_at=datetime.now(UTC),
            acknowledged_by=user_id,
        )
        db.add(ack)
        await db.flush()
        return ack
