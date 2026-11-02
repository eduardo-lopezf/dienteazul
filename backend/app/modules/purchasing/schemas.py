"""Purchasing module Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

OrderStatus = Literal["draft", "sent", "partially_received", "received", "cancelled"]


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tax_id: str | None = Field(default=None, max_length=30)
    contact_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=2000)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    tax_id: str | None = Field(default=None, max_length=30)
    contact_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=2000)
    status: Literal["active", "archived"] | None = None


class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    tax_id: str | None
    contact_name: str | None
    email: str | None
    phone: str | None
    notes: str | None
    status: str


class OrderLineInput(BaseModel):
    item_id: UUID
    #: In the article's base unit, like everything the inventory counts.
    quantity_ordered: Decimal = Field(gt=0, lt=1000000)
    unit_cost: Decimal = Field(ge=0, lt=1000000)


class OrderCreate(BaseModel):
    supplier_id: UUID
    order_date: date
    expected_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[OrderLineInput] = Field(min_length=1, max_length=200)


class OrderUpdate(BaseModel):
    """Only a draft can be changed; the service enforces that."""

    supplier_id: UUID | None = None
    order_date: date | None = None
    expected_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[OrderLineInput] | None = Field(default=None, max_length=200)


class ReceiptLine(BaseModel):
    line_id: UUID
    quantity: Decimal = Field(gt=0, lt=1000000)
    #: Required when the article tracks lots. Created if it is new.
    lot_code: str | None = Field(default=None, max_length=60)
    expires_on: date | None = None


class ReceiptCreate(BaseModel):
    lines: list[ReceiptLine] = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class ReceiptResult(BaseModel):
    order_status: OrderStatus
    lines_received: int
    movement_ids: list[UUID]


class OrderLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    item_name: str
    item_code: str
    base_unit: str
    tracks_lots: bool
    quantity_ordered: Decimal
    quantity_received: Decimal
    quantity_pending: Decimal
    unit_cost: Decimal
    line_total: Decimal


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    status: str
    supplier_id: UUID
    supplier_name: str
    order_date: date
    expected_date: date | None
    notes: str | None
    sent_at: datetime | None
    completed_at: datetime | None
    total: Decimal
    lines: list[OrderLineResponse]
