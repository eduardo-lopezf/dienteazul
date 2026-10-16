"""Liquidations services.

Settling with an associate dentist. Two numbers decide everything and they
are not the same number:

- what the associate **earned** — the work they performed, priced;
- what has been **collected** for that work — what the patient actually paid.

On a 19.000 MXN orthognathic case those two are months apart, and paying a
percentage of the first means the clinic hands out money it has not
received. Most Mexican clinics pay on the second, which is why `collected`
is the default basis — but both are computed and both are shown, because
neither number can be judged without the other.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.plugins.registry import module_registry
from app.core.utils.clinic_time import clinic_date, clinic_day_window
from app.modules.cashbox.models import CashMovement
from app.modules.cashbox.service import MovementService
from app.modules.payments.models import PatientEarnedEntry
from app.modules.payments.service import LedgerService
from app.modules.professionals.models import Professional

from .models import Liquidation, ProfessionalCommission
from .schemas import (
    LiquidationLine,
    LiquidationPreview,
    ProfessionalBrief,
)

CENTS = Decimal("0.01")


class LiquidationError(ValueError):
    """A refusal the caller can fix. Routers turn it into a 422."""


APPS_UNAVAILABLE = (
    "Settlements cannot be calculated: the Payments and Professionals apps must be enabled"
)


def can_calculate() -> bool:
    """Whether what a settlement is made of is running (ADR 0037).

    ``payments`` (what was earned and collected) and ``professionals`` (who
    is paid) are integrated, not required. With either off the settlements
    already issued are read and paid, and no new one is calculated, issued
    or given a percentage.
    """
    return module_registry.is_installed("payments") and module_registry.is_installed(
        "professionals"
    )


def _require_calculation() -> None:
    if not can_calculate():
        raise LiquidationError(APPS_UNAVAILABLE)


class CommissionService:
    """The arrangement with each professional. Mutable; documents freeze it."""

    @staticmethod
    async def list(db: AsyncSession, clinic_id: UUID) -> list[ProfessionalCommission]:
        result = await db.execute(
            select(ProfessionalCommission)
            .options(joinedload(ProfessionalCommission.professional))
            .where(ProfessionalCommission.clinic_id == clinic_id)
        )
        return list(result.unique().scalars().all())

    @staticmethod
    async def get(
        db: AsyncSession, clinic_id: UUID, professional_id: UUID
    ) -> ProfessionalCommission | None:
        result = await db.execute(
            select(ProfessionalCommission)
            .options(joinedload(ProfessionalCommission.professional))
            .where(
                ProfessionalCommission.clinic_id == clinic_id,
                ProfessionalCommission.professional_id == professional_id,
            )
            .execution_options(populate_existing=True)
        )
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def upsert(
        db: AsyncSession, clinic_id: UUID, professional_id: UUID, data: dict
    ) -> ProfessionalCommission:
        _require_calculation()
        professional = await db.scalar(
            select(Professional).where(
                Professional.id == professional_id,
                Professional.clinic_id == clinic_id,
            )
        )
        if professional is None:
            raise LiquidationError("That professional is not in this clinic.")

        existing = await CommissionService.get(db, clinic_id, professional_id)
        if existing is not None:
            for field, value in data.items():
                setattr(existing, field, value)
            await db.flush()
            return existing

        commission = ProfessionalCommission(
            clinic_id=clinic_id, professional_id=professional_id, **data
        )
        db.add(commission)
        await db.flush()
        return commission


class LiquidationService:
    """What a professional is owed for a period, and the document that says so."""

    @staticmethod
    async def preview(
        db: AsyncSession,
        clinic_id: UUID,
        currency: str,
        timezone: str,
        professional_id: UUID,
        date_from: date,
        date_to: date,
    ) -> LiquidationPreview:
        _require_calculation()
        if date_to < date_from:
            raise LiquidationError("The period ends before it starts.")

        professional = await db.scalar(
            select(Professional).where(
                Professional.id == professional_id,
                Professional.clinic_id == clinic_id,
            )
        )
        if professional is None:
            raise LiquidationError("That professional is not in this clinic.")

        # `performed_at` is an instant and the period is a run of clinic
        # days, so the boundary is the clinic's — the same rule every date
        # window in `payments` and `cashbox` already follows.
        window_start, window_end = clinic_day_window(date_from, date_to, timezone)
        result = await db.execute(
            select(PatientEarnedEntry)
            .where(
                PatientEarnedEntry.clinic_id == clinic_id,
                PatientEarnedEntry.professional_id == professional_id,
                PatientEarnedEntry.performed_at >= window_start,
                PatientEarnedEntry.performed_at < window_end,
            )
            .order_by(PatientEarnedEntry.performed_at)
        )
        entries = list(result.scalars().all())

        # Coverage is computed by `payments`, over **all** of each patient's
        # entries and not only this professional's: a patient's money covers
        # their oldest charges first regardless of who did the work, and a
        # walk restricted to one professional would hand them money another
        # had already been credited with.
        coverage = await LedgerService.coverage_by_earned_entry(
            db, clinic_id, sorted({e.patient_id for e in entries})
        )

        lines: list[LiquidationLine] = []
        by_treatment: dict[UUID, LiquidationLine] = {}
        for entry in entries:
            covered = coverage.get(entry.id, Decimal("0"))
            line = by_treatment.get(entry.treatment_id)
            if line is None:
                line = LiquidationLine(
                    treatment_id=entry.treatment_id,
                    description=entry.description,
                    performed_at=entry.performed_at,
                    earned=Decimal("0"),
                    collected=Decimal("0"),
                )
                by_treatment[entry.treatment_id] = line
                lines.append(line)
            # A multi-session treatment earns once per session, so the
            # sessions fold into their treatment rather than each becoming
            # a line nobody asked about.
            line.earned += entry.amount
            line.collected += covered

        earned_total = sum((line.earned for line in lines), Decimal("0"))
        collected_total = sum((line.collected for line in lines), Decimal("0"))

        commission = await CommissionService.get(db, clinic_id, professional_id)
        basis = commission.basis if commission else "collected"
        percent = commission.percent if commission else Decimal("0")

        base_amount = collected_total if basis == "collected" else earned_total
        amount_due = (base_amount * percent / Decimal("100")).quantize(
            CENTS, rounding=ROUND_HALF_UP
        )

        issued = await LiquidationService.issued_for(
            db, clinic_id, professional_id, date_from, date_to
        )

        return LiquidationPreview(
            professional_id=professional_id,
            professional=ProfessionalBrief.model_validate(professional),
            date_from=date_from,
            date_to=date_to,
            currency=currency,
            basis=basis,
            percent=percent,
            earned_total=earned_total,
            collected_total=collected_total,
            base_amount=base_amount,
            amount_due=amount_due,
            lines=lines,
            missing_commission=commission is None,
            issued_id=issued.id if issued else None,
        )

    @staticmethod
    async def issued_for(
        db: AsyncSession,
        clinic_id: UUID,
        professional_id: UUID,
        date_from: date,
        date_to: date,
    ) -> Liquidation | None:
        """The settlement already issued for exactly this period, if any."""
        result = await db.execute(
            select(Liquidation).where(
                Liquidation.clinic_id == clinic_id,
                Liquidation.professional_id == professional_id,
                Liquidation.date_from == date_from,
                Liquidation.date_to == date_to,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        professional_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[Liquidation]:
        filters = [Liquidation.clinic_id == clinic_id]
        if professional_id is not None:
            filters.append(Liquidation.professional_id == professional_id)
        if date_from is not None:
            filters.append(Liquidation.date_to >= date_from)
        if date_to is not None:
            filters.append(Liquidation.date_from <= date_to)
        result = await db.execute(
            select(Liquidation)
            .options(joinedload(Liquidation.professional), joinedload(Liquidation.issuer))
            .where(*filters)
            .order_by(desc(Liquidation.date_from), desc(Liquidation.issued_at))
        )
        return list(result.unique().scalars().all())

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, liquidation_id: UUID) -> Liquidation | None:
        result = await db.execute(
            select(Liquidation)
            .options(joinedload(Liquidation.professional), joinedload(Liquidation.issuer))
            .where(
                Liquidation.id == liquidation_id,
                Liquidation.clinic_id == clinic_id,
            )
            .execution_options(populate_existing=True)
        )
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def issue(
        db: AsyncSession,
        clinic_id: UUID,
        currency: str,
        timezone: str,
        user_id: UUID,
        data: dict,
    ) -> Liquidation:
        professional_id: UUID = data["professional_id"]
        date_from: date = data["date_from"]
        date_to: date = data["date_to"]

        if await LiquidationService.issued_for(db, clinic_id, professional_id, date_from, date_to):
            raise LiquidationError("This period has already been settled with this professional.")

        preview = await LiquidationService.preview(
            db, clinic_id, currency, timezone, professional_id, date_from, date_to
        )
        if preview.missing_commission:
            raise LiquidationError(
                "There is no agreed percentage for this professional yet. "
                "Record the arrangement before settling."
            )

        liquidation = Liquidation(
            clinic_id=clinic_id,
            professional_id=professional_id,
            date_from=date_from,
            date_to=date_to,
            currency=currency,
            basis=preview.basis,
            percent=preview.percent,
            earned_total=preview.earned_total,
            collected_total=preview.collected_total,
            base_amount=preview.base_amount,
            amount_due=preview.amount_due,
            # Frozen: a patient paying tomorrow for work done last fortnight
            # must not change what somebody was already paid.
            lines=[line.model_dump(mode="json") for line in preview.lines],
            notes=(data.get("notes") or "").strip() or None,
            issued_at=datetime.now(UTC),
            issued_by=user_id,
        )
        db.add(liquidation)
        await db.flush()
        return liquidation

    @staticmethod
    async def pay(
        db: AsyncSession,
        clinic_id: UUID,
        currency: str,
        timezone: str,
        user_id: UUID,
        liquidation_id: UUID,
        data: dict,
    ) -> Liquidation | None:
        """Hand the settlement over, writing the till movement if it is cash.

        **A direct call into `cashbox`, in the same transaction, and that is
        deliberate.** The event bus is this project's default for
        cross-module reactions, but this is not a reaction: the payout and
        the till movement are one fact seen twice. A handler running after
        the commit can fail — the bus records it and never retries — and the
        state that leaves behind is a settlement that says *paid* with no
        money having left the drawer. That is the exact silent divergence
        the whole cashbox effort exists to prevent.

        The precedent is `treatment_plan.confirm()`, which calls
        `BudgetService.create_from_plan_snapshot` synchronously for the same
        reason and is documented there as the carve-out. Allowed because
        `cashbox` is in `manifest.depends`.

        Only cash writes a movement. A transfer reaches the associate's bank
        without the drawer ever opening, and inventing a movement for it
        would make the next arqueo come up short by the whole payout.
        """
        liquidation = await LiquidationService.get(db, clinic_id, liquidation_id)
        if liquidation is None:
            return None
        if liquidation.paid_at is not None:
            raise LiquidationError("This settlement has already been paid.")

        method: str = data.get("method") or "cash"
        movement: CashMovement | None = None

        if method == "cash":
            business_date = data.get("business_date") or clinic_date(datetime.now(UTC), timezone)
            # The name is the Professionals app's: left out while it is off.
            name = (
                f"{liquidation.professional.first_name} {liquidation.professional.last_name}".strip()
                if module_registry.is_installed("professionals")
                else ""
            )
            movement = await MovementService.create(
                db,
                clinic_id,
                currency,
                user_id,
                {
                    "business_date": business_date,
                    "direction": "out",
                    "amount": liquidation.amount_due,
                    "category": "professional_payout",
                    # Names the period so the row is readable from the till
                    # screen without following the link back.
                    "concept": (
                        f"Liquidación {name + ' · ' if name else ''}"
                        f"{liquidation.date_from:%d/%m} – {liquidation.date_to:%d/%m}"
                    ),
                    "reference": None,
                    "notes": (data.get("notes") or "").strip() or None,
                },
            )

        liquidation.paid_at = datetime.now(UTC)
        liquidation.paid_by = user_id
        liquidation.payment_method = method
        liquidation.cash_movement_id = movement.id if movement else None
        await db.flush()
        return liquidation

    @staticmethod
    async def unpay(db: AsyncSession, clinic_id: UUID, liquidation_id: UUID) -> Liquidation | None:
        """Undo a payout recorded by mistake.

        Exists because an irreversible mistaken payout is what makes people
        stop trusting a screen. It refuses once the movement has been
        counted: a till movement inside a signed arqueo is part of a number
        somebody stood behind, and the way back is to reopen the day — the
        same rule every other edit in `cashbox` follows.
        """
        liquidation = await LiquidationService.get(db, clinic_id, liquidation_id)
        if liquidation is None:
            return None
        if liquidation.paid_at is None:
            raise LiquidationError("This settlement has not been paid.")

        if liquidation.cash_movement_id is not None:
            movement = await MovementService.get(db, clinic_id, liquidation.cash_movement_id)
            if movement is not None:
                if movement.closing_id is not None:
                    raise LiquidationError(
                        "The till movement for this payout belongs to a day that "
                        "has been counted. Reopen the day first."
                    )
                # Cleared before the delete: the FK is RESTRICT, so the row
                # cannot go while the settlement still points at it.
                liquidation.cash_movement_id = None
                await db.flush()
                # `db.delete` rather than `MovementService.delete`: that one
                # now refuses to touch a `professional_payout` row, and this
                # is the sanctioned way out that the refusal points at.
                await db.delete(movement)
                await db.flush()

        liquidation.paid_at = None
        liquidation.paid_by = None
        liquidation.payment_method = None
        liquidation.cash_movement_id = None
        await db.flush()
        return liquidation
