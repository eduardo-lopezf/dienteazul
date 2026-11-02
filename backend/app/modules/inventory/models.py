"""Inventory module database models.

Five tables, and the shape of them is the decision recorded in ADR 0065:
``inv_movements`` is an append-only ledger and is the truth about stock,
while ``inv_stock_levels`` is a snapshot derived from it and written in
the same transaction. Nothing outside this module writes either one.

Quantities are always in the article's base unit. A purchase
presentation (a box of 100 gloves) carries a factor and is converted on
the way in, so the ledger never has to be read with "...of what?" in
mind.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User


#: Why stock moved. A closed list, because every screen and every report
#: groups by it: `purchase_receipt` stock arriving, `consumption` stock
#: used on a patient or a treatment, `transfer` stock moving between
#: locations, `adjustment` the system being made to agree with the shelf,
#: `expiry_write_off` a lot thrown away, `return` stock going back to the
#: supplier.
MOVEMENT_REASONS = [
    "purchase_receipt",
    "consumption",
    "transfer",
    "adjustment",
    "expiry_write_off",
    "return",
]

#: The only reason allowed to leave a level negative. A physical count can
#: legitimately find less than the system believed, and refusing to record
#: that would make the count useless (ADR 0065).
ADJUSTMENT_REASON = "adjustment"

#: What a location is, for reading a list of them. Not a hierarchy: a
#: clinic has a handful of places where material sits, not a tree.
LOCATION_KINDS = ["warehouse", "cabinet", "fridge", "other"]

#: What an article is for, used only to group the article list. Free-text
#: categories were rejected: every clinic would invent its own spelling of
#: "fungible" and the grouping would stop grouping.
ITEM_CATEGORIES = [
    "consumable",  # guantes, gasas, eyectores
    "restorative",  # composites, adhesivos, cementos
    "anaesthetic",
    "instrument",  # fresas, limas: se gastan, no se esterilizan
    "implant",
    "prosthetic",
    "hygiene",  # desinfectantes, bolsas de esterilización
    "office",
    "other",
]

STATUSES = ["active", "archived"]


class InventoryItem(Base, TimestampMixin):
    """An article the clinic stocks: composite, anaesthetic, gloves, a bur.

    Never a treatment — the catalog owns those, and the list of materials
    one treatment consumes is layer 3, not here.

    ``base_unit`` is what the ledger counts (one glove, one syringe, one
    ml) and ``purchase_presentations`` is how the article is bought
    (``[{"label": "caja de 100", "factor": 100}]``). Storing the factor
    with the presentation rather than on the movement is what keeps the
    ledger readable: a receipt of two boxes is recorded as 200, and the
    box is a detail of the purchase.
    """

    __tablename__ = "inv_items"
    __table_args__ = (
        # The code is how staff and a future import address an article.
        UniqueConstraint("clinic_id", "code", name="uq_inv_item_clinic_code"),
        CheckConstraint(
            "reorder_point IS NULL OR reorder_point >= 0",
            name="ck_inv_item_reorder_point_non_negative",
        ),
        CheckConstraint(
            "reorder_quantity IS NULL OR reorder_quantity > 0",
            name="ck_inv_item_reorder_quantity_positive",
        ),
        # The article list is filtered by category and by status, always
        # within one clinic.
        Index("idx_inv_item_clinic_status", "clinic_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="consumable")
    base_unit: Mapped[str] = mapped_column(String(20), nullable=False)
    purchase_presentations: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    #: Whether every movement of this article must name a lot. Set once,
    #: when the article is created: turning it on later would leave the
    #: stock already on the shelf in no lot at all.
    tracks_lots: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: At or below this, the article belongs on the reorder list. Null
    #: means the clinic has not said, and the article is never low.
    reorder_point: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    reorder_quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    #: Last known cost of one base unit. A convenience for valuing a
    #: receipt, not an accounting figure: the authoritative cost of a
    #: movement is the one stored on the movement.
    cost_per_base_unit: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    #: When this article was last announced as low, so a daily job does
    #: not announce it again every morning. In the database rather than in
    #: a module-level variable because the job runs in one of several
    #: processes (ADR 0051).
    low_stock_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    clinic: Mapped["Clinic"] = relationship("Clinic")


class InventoryLocation(Base, TimestampMixin):
    """Where stock sits: the storeroom, a cabinet, the fridge.

    Several per clinic from the start. The snapshot is keyed by location,
    so adding the concept later would have meant migrating every level and
    every ledger row.

    ``cabinet_id`` may point at an agenda cabinet and deliberately carries
    **no foreign key**: a constraint there would make the inventory
    unusable whenever the Agenda App is off, and this App is meant to
    stand alone (ADR 0037).
    """

    __tablename__ = "inv_locations"
    __table_args__ = (
        UniqueConstraint("clinic_id", "name", name="uq_inv_location_clinic_name"),
        Index("idx_inv_location_clinic_status", "clinic_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="warehouse")
    cabinet_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    #: Where a receipt or a consumption lands when nobody picks a
    #: location. Exactly one per clinic, enforced by the service.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")

    clinic: Mapped["Clinic"] = relationship("Clinic")


class InventoryLot(Base, TimestampMixin):
    """A supplier batch of one article, with the date it stops being usable.

    Expiry is the half of the problem that loses the money, which is why
    lots are in V1 rather than a later layer: anaesthetic and adhesives go
    out of date on a shelf, and without a lot there is nothing to date.
    """

    __tablename__ = "inv_lots"
    __table_args__ = (
        UniqueConstraint("clinic_id", "item_id", "lot_code", name="uq_inv_lot_clinic_item_code"),
        # "What expires in the next N days, in this clinic."
        Index("idx_inv_lot_clinic_expiry", "clinic_id", "expires_on"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    item_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inv_items.id"), nullable=False, index=True
    )
    lot_code: Mapped[str] = mapped_column(String(60), nullable=False)
    #: Null for a lot the supplier ships without a date. The article still
    #: tracks it, it simply never appears on the expiry list.
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: Same purpose as ``InventoryItem.low_stock_notified_at``.
    expiry_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    item: Mapped["InventoryItem"] = relationship("InventoryItem")


class InventoryMovement(Base, TimestampMixin):
    """One line of the ledger. Append-only: the truth about stock (ADR 0065).

    A movement is never updated and never deleted. A mistake is corrected
    by posting the opposite movement with ``reason='adjustment'`` and a
    note saying why, so the record keeps both facts — what was believed
    and what was found. ``updated_at`` comes from the mixin and never
    changes; it is there for table symmetry, not for use.

    ``source_ref`` records what caused the movement without a foreign key
    into another module's tables: ``{"kind": "appointment", "id": "..."}``.
    Opaque on purpose (ADR 0039) — the inventory does not know what an
    appointment is, and a consumption posted twice for the same cause is
    recognised by this value rather than by a constraint it cannot
    declare.
    """

    __tablename__ = "inv_movements"
    __table_args__ = (
        CheckConstraint("quantity_base <> 0", name="ck_inv_movement_quantity_non_zero"),
        # The article detail screen: this article's history, newest first.
        Index("idx_inv_movement_clinic_item", "clinic_id", "item_id", "created_at"),
        # The ledger screen: everything that moved, newest first.
        Index("idx_inv_movement_clinic_created", "clinic_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    item_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inv_items.id"), nullable=False
    )
    location_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inv_locations.id"), nullable=False
    )
    lot_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inv_lots.id"), nullable=True
    )
    #: Signed, in the article's base unit. Positive is stock arriving,
    #: negative is stock leaving. A sign rather than a direction column
    #: because this is a ledger and the sum of it is the answer.
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The user who posted it. Nullable because a scheduled write-off has
    #: no human behind it.
    performed_by: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    #: What one base unit cost on this movement: the supplier's price on
    #: a receipt, the article's weighted average on anything leaving the
    #: shelf, stamped when it moved. That is what lets a report of a past
    #: period give the same answer next year (layer 5). Null on movements
    #: written before this existed, and on an article nobody priced —
    #: `MaterialCostLine.unpriced` counts those rather than guessing.
    cost_per_base_unit: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)

    item: Mapped["InventoryItem"] = relationship("InventoryItem")
    location: Mapped["InventoryLocation"] = relationship("InventoryLocation")
    lot: Mapped["InventoryLot | None"] = relationship("InventoryLot")
    performer: Mapped["User | None"] = relationship("User")


class ImplantTrace(Base, TimestampMixin):
    """Which batch of which device went into which patient.

    The one table in this module that holds patient data, and it holds
    it because the law says it must: a medical device has to be
    traceable from the manufacturer's batch to the person carrying it,
    so that a manufacturer's recall can be answered with a list of
    names. That is also why it is **not erasable** on request — see
    ``privacy.py`` and ADR 0026.

    ``patient_id`` and ``professional_id`` carry no foreign key, like
    every other outward link in this module: the trace must survive the
    Patients App being switched off, and it must survive the patient
    row being erased. The names are read through the
    ``PatientDirectory`` contract when that App is running.

    ``movement_id`` ties the trace to the ledger line that took the
    device off the shelf, so the two can never disagree about whether it
    was used (ADR 0065).
    """

    __tablename__ = "inv_implant_traces"
    __table_args__ = (
        # The recall question: "this batch was withdrawn — who has it?"
        Index("idx_inv_trace_clinic_lot", "clinic_id", "lot_id"),
        # The clinical question: "what is this patient carrying?"
        Index("idx_inv_trace_clinic_patient", "clinic_id", "patient_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    #: A ``patients.id``, deliberately without a FK (see the docstring).
    patient_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    item_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inv_items.id"), nullable=False
    )
    #: Required: a trace without a batch traces nothing.
    lot_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inv_lots.id"), nullable=False
    )
    #: The consumption that took it off the shelf.
    movement_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inv_movements.id"), nullable=False
    )
    placed_on: Mapped[date] = mapped_column(Date, nullable=False)
    #: FDI notation, when the device went in a specific place.
    tooth_number: Mapped[int | None] = mapped_column(Integer)
    #: The device's own serial or UDI, when the package carries one.
    serial_number: Mapped[str | None] = mapped_column(String(80))
    #: A ``professionals.id``; no FK, same reason as ``patient_id``.
    professional_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True))
    notes: Mapped[str | None] = mapped_column(Text)

    item: Mapped["InventoryItem"] = relationship("InventoryItem")
    lot: Mapped["InventoryLot"] = relationship("InventoryLot")


class TreatmentMaterial(Base, TimestampMixin):
    """What one catalogue treatment is expected to consume.

    The *escandallo*. It lives here, in the inventory, rather than on the
    catalogue item, for one reason: switch the Treatments App off and
    this stays inert but intact; switch the inventory off and the
    catalogue never learns that stock exists. A list of materials is an
    inventory concept that happens to be keyed by a treatment.

    ``catalog_item_id`` therefore carries **no foreign key**. A
    constraint against ``treatment_catalog_items`` would make the
    inventory unusable whenever Treatments is disabled, which is exactly
    what this module refuses to be (ADR 0037). Rows whose treatment was
    deleted simply stop matching anything; they are harmless and the
    screen shows them as unknown.
    """

    __tablename__ = "inv_treatment_materials"
    __table_args__ = (
        UniqueConstraint(
            "clinic_id", "catalog_item_id", "item_id", name="uq_inv_material_treatment_item"
        ),
        CheckConstraint("quantity_base > 0", name="ck_inv_material_quantity_positive"),
        # "What does this treatment consume?", the only question asked.
        Index("idx_inv_material_clinic_treatment", "clinic_id", "catalog_item_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    #: A ``treatment_catalog_items.id``, deliberately without a FK.
    catalog_item_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    item_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inv_items.id"), nullable=False
    )
    #: How much of the article one treatment uses, in its base unit.
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)

    item: Mapped["InventoryItem"] = relationship("InventoryItem")


class InventoryStockLevel(Base, TimestampMixin):
    """What is on hand of one article, in one location, of one lot.

    A cache of the ledger, written in the same transaction as the movement
    that changes it, so it is never stale and never disagrees. Recomputing
    it from ``inv_movements`` is always allowed and always safe; writing it
    from anywhere but ``StockService.post`` is not.

    The unique constraint is ``NULLS NOT DISTINCT`` (PostgreSQL 15+):
    without that, every movement of an article with no lot would insert a
    *new* row — Postgres treats two NULLs as different values — and the
    article's stock would be scattered across one row per movement while
    every constraint still passed.
    """

    __tablename__ = "inv_stock_levels"
    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "location_id",
            "lot_id",
            name="uq_inv_stock_level_item_location_lot",
            postgresql_nulls_not_distinct=True,
        ),
        # The stock screen: everything this clinic holds.
        Index("idx_inv_stock_level_clinic_item", "clinic_id", "item_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    item_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inv_items.id"), nullable=False
    )
    location_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inv_locations.id"), nullable=False
    )
    lot_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inv_lots.id"), nullable=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=0)

    item: Mapped["InventoryItem"] = relationship("InventoryItem")
    location: Mapped["InventoryLocation"] = relationship("InventoryLocation")
    lot: Mapped["InventoryLot | None"] = relationship("InventoryLot")
