"""Liquidations module Pydantic schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.plugins.registry import module_registry

CommissionBasis = Literal["collected", "earned"]
PaymentMethod = Literal["cash", "transfer", "other"]


class UserBrief(BaseModel):
    id: UUID
    first_name: str
    last_name: str

    model_config = ConfigDict(from_attributes=True)


class ProfessionalBrief(BaseModel):
    id: UUID
    first_name: str
    last_name: str

    model_config = ConfigDict(from_attributes=True)


class _HidesProfessional(BaseModel):
    """With Professionals off its records are not shown (ADR 0037).

    ``professional_id`` is this module's own column and stays.
    """

    professional: ProfessionalBrief | None = None

    @model_validator(mode="after")
    def _hide_professional_when_off(self) -> "_HidesProfessional":
        if not module_registry.is_installed("professionals"):
            self.professional = None
        return self


# --- The arrangement ---------------------------------------------------


class CommissionUpsert(BaseModel):
    basis: CommissionBasis = "collected"
    percent: Decimal = Field(ge=0, le=100)
    notes: str | None = None


class CommissionResponse(_HidesProfessional):
    id: UUID
    professional_id: UUID
    basis: str
    percent: Decimal
    notes: str | None = None
    professional: ProfessionalBrief | None = None

    model_config = ConfigDict(from_attributes=True)


# --- The settlement ----------------------------------------------------


class LiquidationLine(BaseModel):
    """One piece of work, with what it earned and what has been collected.

    `treatment_id` rather than a patient: this document goes to an
    associate and names the work, not the people. The module does not
    depend on `patients` and there is no reason it should.
    """

    treatment_id: UUID
    description: str | None = None
    performed_at: datetime
    earned: Decimal
    collected: Decimal

    @property
    def pending(self) -> Decimal:
        return self.earned - self.collected


class LiquidationPreview(_HidesProfessional):
    """What a settlement would say if it were issued right now.

    Recalculated on every read, and that is correct while nobody has been
    paid. `LiquidationResponse` is the same shape frozen.
    """

    professional_id: UUID
    professional: ProfessionalBrief | None = None
    date_from: date
    date_to: date
    currency: str

    basis: str
    percent: Decimal

    #: Both axes, always. The gap between them is the whole question.
    earned_total: Decimal
    collected_total: Decimal
    base_amount: Decimal
    amount_due: Decimal

    lines: list[LiquidationLine]
    #: True when this professional has no arrangement recorded yet — the
    #: figures are the work, and the percentage is zero until somebody says.
    missing_commission: bool = False
    #: Set when the period already carries an issued settlement.
    issued_id: UUID | None = None


class LiquidationIssue(BaseModel):
    professional_id: UUID
    date_from: date
    date_to: date
    notes: str | None = None


class LiquidationPay(BaseModel):
    """Handing the settlement over.

    `business_date` only matters for a cash payout — it is the till day the
    movement lands on. Left out, it is the clinic's today; given a day that
    has already been counted, the movement surfaces as a late entry, which
    is the right answer and costs this module nothing because `cashbox`
    already handles it.
    """

    method: PaymentMethod = "cash"
    business_date: date | None = None
    notes: str | None = Field(default=None, max_length=300)


class LiquidationResponse(_HidesProfessional):
    id: UUID
    professional_id: UUID
    professional: ProfessionalBrief | None = None
    date_from: date
    date_to: date
    currency: str
    basis: str
    percent: Decimal
    earned_total: Decimal
    collected_total: Decimal
    base_amount: Decimal
    amount_due: Decimal
    lines: list[LiquidationLine]
    notes: str | None = None
    issued_at: datetime
    issued_by: UUID
    issuer: UserBrief | None = None

    paid_at: datetime | None = None
    payment_method: str | None = None
    payer: UserBrief | None = None
    #: The till movement the payout wrote, when it was paid in cash.
    cash_movement_id: UUID | None = None

    model_config = ConfigDict(from_attributes=True)
