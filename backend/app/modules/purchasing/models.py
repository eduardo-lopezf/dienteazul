"""Purchasing module database models.

Three tables: who the clinic buys from, what it ordered, and what each
line of that order was for. Receiving is **not** a table — it is a
movement in the inventory's ledger, which stays the only place stock
changes (ADR 0065). What lives here is the promise ("20 boxes are
coming, at this price") and what remains of it.

Supplier contact details are a counterparty's, which may be a sole
trader's: they carry the same classification `billing` gives the
customer side (ADR 0025).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.core.privacy import DataClass, PiiKind, pii
from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User
    from app.modules.inventory.models import InventoryItem


#: Where an order is. `partially_received` exists because a supplier
#: sends what it has: an order half delivered is neither open nor done,
#: and collapsing it into either loses the half that is still coming.
ORDER_STATUSES = ["draft", "sent", "partially_received", "received", "cancelled"]

#: Statuses that still expect goods. Used by the "what is coming" views.
OPEN_STATUSES = ["draft", "sent", "partially_received"]


class Supplier(Base, TimestampMixin):
    """Who the clinic buys from."""

    __tablename__ = "pur_suppliers"
    __table_args__ = (
        UniqueConstraint("clinic_id", "name", name="uq_pur_supplier_clinic_name"),
        Index("idx_pur_supplier_clinic_status", "clinic_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False, info=pii(PiiKind.NAME, data_class=DataClass.FINANCIAL)
    )
    tax_id: Mapped[str | None] = mapped_column(
        String(30), info=pii(PiiKind.NATIONAL_ID, data_class=DataClass.FINANCIAL)
    )
    contact_name: Mapped[str | None] = mapped_column(
        String(200), info=pii(PiiKind.NAME, data_class=DataClass.FINANCIAL)
    )
    email: Mapped[str | None] = mapped_column(
        String(255), info=pii(PiiKind.EMAIL, data_class=DataClass.FINANCIAL)
    )
    phone: Mapped[str | None] = mapped_column(
        String(30), info=pii(PiiKind.PHONE, data_class=DataClass.FINANCIAL)
    )
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")

    clinic: Mapped["Clinic"] = relationship("Clinic")


class PurchaseOrder(Base, TimestampMixin):
    """What was ordered from one supplier, on one day.

    ``number`` is the clinic's own sequence and is what staff and the
    supplier say out loud. It is assigned under an advisory lock, so two
    people pressing *send* at the same moment in different processes
    cannot be handed the same one.
    """

    __tablename__ = "pur_orders"
    __table_args__ = (
        UniqueConstraint("clinic_id", "number", name="uq_pur_order_clinic_number"),
        # The list screen: this clinic's orders, newest first, filtered
        # by where they are.
        Index("idx_pur_order_clinic_status", "clinic_id", "status", "order_date"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    supplier_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pur_suppliers.id"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: When the supplier said it would arrive. Null when nobody asked.
    expected_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When the last outstanding line was received.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    supplier: Mapped["Supplier"] = relationship("Supplier")
    creator: Mapped["User | None"] = relationship("User")
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        "PurchaseOrderLine",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLine.created_at",
    )


class PurchaseOrderLine(Base, TimestampMixin):
    """One article on an order, with what it costs and what has arrived.

    Quantities are in the article's **base unit**, like everything else
    the inventory counts: the presentation a supplier sells in is
    converted when the line is written, so the order and the ledger speak
    the same language.

    ``item_id`` is a foreign key into ``inv_items``, which is allowed
    because `inventory` is in this module's ``depends``. Receiving does
    not write stock here — it calls the inventory's service, so the
    ledger stays the only place stock changes.
    """

    __tablename__ = "pur_order_lines"
    __table_args__ = (
        CheckConstraint("quantity_ordered > 0", name="ck_pur_line_quantity_positive"),
        CheckConstraint("quantity_received >= 0", name="ck_pur_line_received_non_negative"),
        CheckConstraint("unit_cost >= 0", name="ck_pur_line_cost_non_negative"),
        Index("idx_pur_line_order", "order_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    order_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pur_orders.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inv_items.id"), nullable=False
    )
    quantity_ordered: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    order: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", back_populates="lines")
    item: Mapped["InventoryItem"] = relationship("InventoryItem")
