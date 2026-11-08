"""Commissions module Pydantic schemas."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

CommissionBasis = Literal["collected", "earned"]


class RateIn(BaseModel):
    catalog_item_id: UUID
    percent: Decimal = Field(ge=0, le=100)


class AgreementIn(BaseModel):
    basis: CommissionBasis = "collected"
    default_percent: Decimal | None = Field(default=None, ge=0, le=100)
    rates: list[RateIn] = Field(default_factory=list, max_length=500)
    notes: str | None = None


class RateOut(BaseModel):
    catalog_item_id: UUID
    percent: Decimal
    #: Absent while the Treatments App is off: the rate stands, unnamed.
    internal_code: str | None = None
    names: dict[str, str] | None = None


class AgreementOut(BaseModel):
    professional_id: UUID
    #: False when nothing has been agreed yet — the rest is the empty form.
    configured: bool
    basis: str = "collected"
    default_percent: Decimal | None = None
    rates: list[RateOut] = Field(default_factory=list)
    notes: str | None = None


class TreatmentOption(BaseModel):
    id: UUID
    internal_code: str
    names: dict[str, str]
