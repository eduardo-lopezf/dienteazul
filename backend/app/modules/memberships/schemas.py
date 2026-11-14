"""Memberships module Pydantic schemas."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

PlanPeriod = Literal["monthly", "annual"]
BenefitKind = Literal["included", "discount"]
#: The methods a payment takes (`payments`), restated: another App's schema
#: is not imported (ADR 0039).
PaymentMethod = Literal["cash", "card", "bank_transfer", "direct_debit", "insurance", "other"]


class BenefitIn(BaseModel):
    catalog_item_id: UUID
    kind: BenefitKind
    quantity: int | None = Field(default=None, ge=1, le=100)
    discount_percent: Decimal | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _matches_kind(self) -> "BenefitIn":
        if self.kind == "included" and self.quantity is None:
            raise ValueError("an included benefit needs a quantity")
        if self.kind == "discount" and self.discount_percent is None:
            raise ValueError("a discount benefit needs a percentage")
        return self


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    fee: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    period: PlanPeriod
    general_discount_percent: Decimal | None = Field(default=None, ge=0, le=100)
    benefits: list[BenefitIn] = Field(default_factory=list, max_length=200)


class BenefitOut(BaseModel):
    catalog_item_id: UUID
    kind: str
    quantity: int | None = None
    discount_percent: Decimal | None = None
    #: Absent while the Treatments App is off: the benefit stands, unnamed.
    internal_code: str | None = None
    names: dict[str, str] | None = None


class PlanOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    fee: Decimal
    period: str
    general_discount_percent: Decimal | None
    status: str
    benefits: list[BenefitOut]


class TreatmentOption(BaseModel):
    id: UUID
    internal_code: str
    names: dict[str, str]


class FeePaymentIn(BaseModel):
    method: PaymentMethod
    payment_date: date
    reference: str | None = Field(default=None, max_length=100)


class EnrollIn(BaseModel):
    plan_id: UUID
    starts_on: date
    payment: FeePaymentIn


class RenewIn(BaseModel):
    payment: FeePaymentIn


class ChangePlanIn(BaseModel):
    plan_id: UUID


class PeriodOut(BaseModel):
    id: UUID
    starts_on: date
    ends_on: date
    amount: Decimal
    refunded_amount: Decimal
    status: str
    plan_name: str
    payment_id: UUID | None


class IncludedUsage(BaseModel):
    catalog_item_id: UUID
    quantity: int
    used: int
    internal_code: str | None = None
    names: dict[str, str] | None = None


class MembershipOut(BaseModel):
    id: UUID
    patient_id: UUID
    plan_id: UUID
    plan_name: str
    #: ``active`` (benefits apply), ``expired`` (fee overdue) or ``cancelled``.
    state: str
    status: str
    started_on: date
    paid_through: date | None
    #: Last day benefits apply, grace included.
    covered_until: date | None
    cycle_start: date
    general_discount_percent: Decimal | None
    included: list[IncludedUsage]
    discounts: list[BenefitOut]
    periods: list[PeriodOut]
    payments_available: bool


class PatientMembershipOut(BaseModel):
    """``membership`` is ``None`` when the patient never had one."""

    membership: MembershipOut | None
