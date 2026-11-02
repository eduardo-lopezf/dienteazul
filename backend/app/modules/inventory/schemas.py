"""Inventory module Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ItemCategory = Literal[
    "consumable",
    "restorative",
    "anaesthetic",
    "instrument",
    "implant",
    "prosthetic",
    "hygiene",
    "office",
    "other",
]
LocationKind = Literal["warehouse", "cabinet", "fridge", "other"]
MovementReason = Literal[
    "purchase_receipt",
    "consumption",
    "transfer",
    "adjustment",
    "expiry_write_off",
    "return",
]
#: What a caller may post directly. ``transfer`` is excluded on purpose:
#: it is two movements and has its own endpoint, so accepting it here
#: would let a caller post half a transfer.
PostableReason = Literal[
    "purchase_receipt",
    "consumption",
    "adjustment",
    "expiry_write_off",
    "return",
]


class PurchasePresentation(BaseModel):
    """How an article is bought, and how many base units that is."""

    label: str = Field(max_length=60)
    factor: Decimal = Field(gt=0, le=100000)


class ItemCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    base_unit: str = Field(min_length=1, max_length=20)
    category: ItemCategory = "consumable"
    purchase_presentations: list[PurchasePresentation] = Field(default_factory=list)
    tracks_lots: bool = False
    reorder_point: Decimal | None = Field(default=None, ge=0)
    reorder_quantity: Decimal | None = Field(default=None, gt=0)
    cost_per_base_unit: Decimal | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2000)


class ItemUpdate(BaseModel):
    """``tracks_lots`` is absent on purpose.

    Turning lot tracking on for an article that already has stock would
    leave what is on the shelf in no lot at all, and turning it off would
    orphan the lots already recorded. It is decided when the article is
    created.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    base_unit: str | None = Field(default=None, min_length=1, max_length=20)
    category: ItemCategory | None = None
    purchase_presentations: list[PurchasePresentation] | None = None
    reorder_point: Decimal | None = Field(default=None, ge=0)
    reorder_quantity: Decimal | None = Field(default=None, gt=0)
    cost_per_base_unit: Decimal | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2000)
    status: Literal["active", "archived"] | None = None


class ItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    category: str
    base_unit: str
    purchase_presentations: list[PurchasePresentation]
    tracks_lots: bool
    reorder_point: Decimal | None
    reorder_quantity: Decimal | None
    cost_per_base_unit: Decimal | None
    notes: str | None
    status: str
    created_at: datetime


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: LocationKind = "warehouse"
    cabinet_id: UUID | None = None
    is_default: bool = False


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    kind: LocationKind | None = None
    cabinet_id: UUID | None = None
    is_default: bool | None = None
    status: Literal["active", "archived"] | None = None


class LocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    kind: str
    cabinet_id: UUID | None
    is_default: bool
    status: str


class LotCreate(BaseModel):
    lot_code: str = Field(min_length=1, max_length=60)
    expires_on: date | None = None


class LotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    lot_code: str
    expires_on: date | None


class MovementCreate(BaseModel):
    item_id: UUID
    location_id: UUID | None = None
    lot_id: UUID | None = None
    #: Signed and in base units for an adjustment, which is the only
    #: reason that can go either way. For every other reason the sign is
    #: implied by the reason and a positive quantity is expected.
    quantity_base: Decimal = Field(gt=-1000000, lt=1000000)
    reason: PostableReason
    note: str | None = Field(default=None, max_length=1000)
    cost_per_base_unit: Decimal | None = Field(default=None, ge=0)
    source_ref: dict | None = None


class TransferCreate(BaseModel):
    item_id: UUID
    from_location_id: UUID
    to_location_id: UUID
    lot_id: UUID | None = None
    quantity_base: Decimal = Field(gt=0, lt=1000000)
    note: str | None = Field(default=None, max_length=1000)


class CountLine(BaseModel):
    item_id: UUID
    location_id: UUID
    lot_id: UUID | None = None
    #: What was actually on the shelf. The difference against the snapshot
    #: is what gets posted, so a line that agrees posts nothing.
    counted_quantity: Decimal = Field(ge=0, lt=1000000)


class CountCreate(BaseModel):
    lines: list[CountLine] = Field(min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=1000)


class CountResult(BaseModel):
    lines_counted: int
    adjustments_posted: int
    movement_ids: list[UUID]


class UserBrief(BaseModel):
    """Enough of a user to put a name on a ledger line.

    Field names are the owning columns' names, so the PII classification
    on those columns still applies wherever this is serialized (ADR 0025).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str
    last_name: str


class MovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    item_name: str
    location_id: UUID
    location_name: str
    lot_id: UUID | None
    lot_code: str | None
    quantity_base: Decimal
    reason: str
    note: str | None
    source_ref: dict | None
    performed_by: UUID | None
    #: Null for a movement with no human behind it — a scheduled
    #: write-off — and for one whose user has since been removed.
    performed_by_user: UserBrief | None = None
    cost_per_base_unit: Decimal | None
    created_at: datetime


class ImplantRecord(BaseModel):
    """Recording a device placed in a patient."""

    patient_id: UUID
    item_id: UUID
    lot_id: UUID
    placed_on: date
    location_id: UUID | None = None
    #: Almost always one; a bridge may take two of the same reference.
    quantity: Decimal = Field(default=Decimal("1"), gt=0, le=20)
    tooth_number: int | None = Field(default=None, ge=11, le=85)
    serial_number: str | None = Field(default=None, max_length=80)
    professional_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=1000)


class ImplantTraceResponse(BaseModel):
    id: UUID
    patient_id: UUID
    #: Absent when the Patients App is off: the id is ours, the name is
    #: not (ADR 0037). Under the owning columns' names so the redactor
    #: tokenizes it (ADR 0025).
    first_name: str | None = None
    last_name: str | None = None
    item_id: UUID
    item_code: str
    item_name: str
    lot_id: UUID
    lot_code: str
    expires_on: date | None
    placed_on: date
    tooth_number: int | None
    serial_number: str | None
    notes: str | None


class MaterialLine(BaseModel):
    item_id: UUID
    #: Per treatment, in the article's base unit.
    quantity_base: Decimal = Field(gt=0, lt=100000)


class MaterialsSet(BaseModel):
    """The treatment's whole list, replacing whatever was there."""

    lines: list[MaterialLine] = Field(max_length=50)


class MaterialResponse(BaseModel):
    item_id: UUID
    item_code: str
    item_name: str
    base_unit: str
    tracks_lots: bool
    quantity_base: Decimal


class TreatmentMaterialsResponse(BaseModel):
    catalog_item_id: UUID
    #: Absent when the Treatments App is off: the ids are still ours, the
    #: names are not (ADR 0037).
    treatment_code: str | None
    treatment_name: str | None
    lines: list[MaterialResponse]


class CatalogTreatmentOption(BaseModel):
    """A treatment to pick from, read through the contract."""

    id: UUID
    internal_code: str
    name: str


class StockLine(BaseModel):
    """One row of the stock screen: an article, somewhere, of some lot."""

    item_id: UUID
    item_code: str
    item_name: str
    category: str
    base_unit: str
    location_id: UUID
    location_name: str
    lot_id: UUID | None
    lot_code: str | None
    expires_on: date | None
    quantity: Decimal
    #: Across every location and lot, so a reorder decision is not taken
    #: from one cabinet's shelf.
    item_total: Decimal
    reorder_point: Decimal | None
    is_low: bool
    days_to_expiry: int | None


class StockAlerts(BaseModel):
    low_stock: list[StockLine]
    expiring: list[StockLine]
    expired: list[StockLine]


class ReconcileResult(BaseModel):
    """What a recomputation of the snapshot from the ledger changed.

    ``corrected`` is expected to be zero. Anything else means a write
    reached ``inv_stock_levels`` outside ``StockService.post``, which is
    the one thing ADR 0065 forbids.
    """

    levels_checked: int
    corrected: int
    removed: int
