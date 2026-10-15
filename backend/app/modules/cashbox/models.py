"""Cashbox module database models."""

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User


# Which way the money went. Deliberately not a sign on the amount: a
# negative number in a till listing is read as a correction, and half the
# rows here would carry one.
MOVEMENT_DIRECTIONS = ["in", "out"]

# A short, closed list. Long enough that the common reasons do not all land
# in `other`, short enough that nobody has to think at the counter — the
# concept field carries the detail. Reporting groups by this, so growing it
# later is cheap and shrinking it is not.
MOVEMENT_CATEGORIES = [
    "lab",  # pagado al mensajero del laboratorio
    "supplies",  # material comprado con dinero del cajón
    "advance",  # adelanto o préstamo a alguien de la clínica
    # Pago de una liquidación a un asociado. Distinta de `advance` a
    # propósito: un adelanto se descuenta después y una liquidación ya es el
    # pago, y un informe que no las separa no sirve para ninguna de las dos.
    # `liquidations` escribe la fila; la categoría vive aquí porque es esta
    # tabla la que tiene que poder agruparla.
    "professional_payout",
    "bank_deposit",  # sale del cajón hacia el banco
    "float_adjustment",  # se mete o se saca cambio del fondo
    "other",
]


#: How a movement was paid. `insurance` is deliberately absent: it is a way
#: money reaches a clinic, never a way the clinic spends it.
MOVEMENT_METHODS = ["cash", "card", "bank_transfer", "direct_debit", "other"]


class CashMovement(Base, TimestampMixin):
    """Money entering or leaving the clinic that is not a patient payment.

    This is what makes a cash count possible at all. A till is emptied all
    day by things `payments` will never know about — the lab courier is
    paid, gloves are bought, an assistant takes an advance, change is added
    from the safe. Without somewhere to record them the counted cash can
    never match the expected cash, the difference is a non-zero number
    every single day, and the arqueo gets abandoned within the fortnight as
    "it always says there's an error".

    Rows are free to be edited or deleted while the day is open and frozen
    the moment it is closed: `closing_id` is stamped by the closing and is
    what makes the movement part of an accounting record rather than a note
    someone left. Phase 1 ships without closings, so the column is nullable
    and always null — the FK arrives with `CashClosing` and nothing here
    changes when it does.
    """

    __tablename__ = "cash_movements"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_cash_movement_amount_positive"),
        # The list screen asks exactly one question: what moved on this day
        # in this clinic. `business_date` is a DATE in the clinic's own
        # calendar, so no conversion happens at read time.
        Index("idx_cash_movement_clinic_date", "clinic_id", "business_date"),
        # Closing a day stamps every open movement of that day, and a
        # period view walks movements by the closing that owns them.
        Index("idx_cash_movement_closing", "closing_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    # The clinic's calendar day this belongs to, not an instant: the till is
    # counted per day, and `created_at` would put a movement recorded at
    # 00:10 into the wrong count for any clinic west of Greenwich.
    business_date: Mapped[date] = mapped_column(Date)

    direction: Mapped[str] = mapped_column(String(3))
    # How the money moved. `cash` is the only one the arqueo counts — the
    # rest never touch the drawer.
    #
    # The table was cash-only for its first three revisions, which is why
    # the column defaults to `cash` and why every historical row is
    # correct without a backfill. It exists because a clinic's money does
    # not all pass through a drawer: the lab paid by transfer, the rent,
    # the supplier on thirty days. Without somewhere to put them the
    # system could only ever answer half of "how did the month go" — every
    # figure it had was an inflow.
    method: Mapped[str] = mapped_column(String(20), default="cash", server_default="cash")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Snapshot of `Clinic.currency`, same rule as `Payment`: a clinic that
    # ever switches currency keeps its history in the old one.
    currency: Mapped[str] = mapped_column(String(3))

    category: Mapped[str] = mapped_column(String(20))
    # Required, and free text on purpose. "supplies" is what a report can
    # group by; "guantes de nitrilo, farmacia de la esquina" is what makes
    # the row mean something to whoever reads it in March.
    concept: Mapped[str] = mapped_column(String(160))
    reference: Mapped[str | None] = mapped_column(String(100), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    # Set when the day is closed. Null means the day is still open and the
    # row can still be corrected. RESTRICT rather than CASCADE: a closing is
    # never deleted, and if one ever were, taking its movements with it
    # would erase the day it counted.
    closing_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cash_closings.id", ondelete="RESTRICT"), default=None
    )

    recorded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])
    recorder: Mapped["User"] = relationship(foreign_keys=[recorded_by])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<CashMovement {self.business_date} {self.direction} "
            f"{self.amount} {self.method} {self.category}>"
        )


# A closing is either the day's standing count or a superseded one. There is
# no "open" state: a day with no row is open, which is the same thing and one
# fewer thing to keep true.
CLOSING_STATUSES = ["closed", "reopened"]


class CashClosing(Base, TimestampMixin):
    """One arqueo: the day someone counted the drawer and signed it off.

    This is the act the whole module exists for. `payments` can already say
    what came in; only a person can say what is actually there, and the gap
    between the two is the only number here that no query could produce.

    **Every figure is stored, not derived.** `expected_cash` is what the
    system believed at the moment of the count, and it stays that even after
    someone back-dates a payment into the day — the whole point of a signed
    count is that it stops moving. `snapshot` holds the full breakdown for
    the same reason: a period view reads the frozen record, never a fresh
    query over rows that have changed since.

    **Reopening supersedes rather than deletes.** The row is marked
    `reopened` and a fresh one is written by the next close, so the history
    of counts survives. That history is what answers the question an owner
    actually has — 20 pesos short on a Tuesday is noise, 500 short every
    Friday is a signal — and a delete would erase exactly the evidence.
    """

    __tablename__ = "cash_closings"
    __table_args__ = (
        CheckConstraint("opening_float >= 0", name="ck_cash_closing_opening_float"),
        CheckConstraint("counted_cash >= 0", name="ck_cash_closing_counted_cash"),
        CheckConstraint("closing_float >= 0", name="ck_cash_closing_closing_float"),
        # At most one standing count per day. Partial, so the superseded
        # rows a reopen leaves behind do not collide with the new one — the
        # database holds the rule rather than the service remembering to.
        Index(
            "uq_cash_closing_standing_day",
            "clinic_id",
            "business_date",
            unique=True,
            postgresql_where=text("status = 'closed'"),
        ),
        Index("idx_cash_closing_clinic_date", "clinic_id", "business_date"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    business_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="closed")

    currency: Mapped[str] = mapped_column(String(3))

    # What the drawer held at the start. Defaults to yesterday's
    # `closing_float`, so the chain runs itself and nobody retypes it.
    opening_float: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    # What the system believed, at the moment of the count.
    expected_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # What the person counted.
    counted_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Stored, not computed on read: it is the figure that was signed off.
    difference: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # What is left in the drawer for tomorrow; the rest was taken out.
    closing_float: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    # The full breakdown as it stood: collections by method, refunds,
    # movements in and out, and their counts. A period view reads this.
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Required by the service whenever `difference` is not zero. A count
    # that does not match and says nothing is a number nobody can act on.
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    # Set when this count is superseded. Throwing away a signed count is an
    # act with an owner, so it records one.
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    reopened_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), default=None)
    reopen_reason: Mapped[str | None] = mapped_column(Text, default=None)

    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])
    closer: Mapped["User"] = relationship(foreign_keys=[closed_by])
    reopener: Mapped["User | None"] = relationship(foreign_keys=[reopened_by])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CashClosing {self.business_date} {self.status} diff={self.difference}>"


# What kind of thing landed late. Not a foreign key to anything: two of the
# three live in `payments`, and a cross-module FK from here would be a
# dependency the manifest does not declare.
LATE_ENTRY_KINDS = ["payment", "refund", "movement"]


class LateEntryAck(Base, TimestampMixin):
    """Somebody looked at a late entry and decided what to do about it.

    A payment written on Monday against a Friday that was already counted
    is allowed — forbidding it only makes people file it under today and
    lie about the date. What it cannot be is silent: the count Friday
    signed no longer describes Friday.

    So the entry is surfaced, and this row is how it stops being surfaced.
    Without somewhere to say *seen, it goes into next week's* the list only
    grows, and a warning that is always on is a warning nobody reads — the
    same failure that kills an arqueo whose difference is never zero.

    The entry is addressed by `(kind, entry_id)` and **not** by a foreign
    key: two of the three kinds live in `payments`, and an FK from here
    would be a dependency the manifest does not declare.
    """

    __tablename__ = "cash_late_entry_acks"
    __table_args__ = (
        UniqueConstraint("clinic_id", "entry_kind", "entry_id", name="uq_cash_late_entry_ack"),
        Index("idx_cash_late_ack_clinic_date", "clinic_id", "business_date"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    entry_kind: Mapped[str] = mapped_column(String(10))
    entry_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True))
    #: The clinic day the entry belongs to — what makes it late.
    business_date: Mapped[date] = mapped_column(Date)

    #: What was decided. Free text, and required by the service: "seen" is
    #: not a decision anybody can act on three months later.
    resolution: Mapped[str] = mapped_column(String(300))

    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])
    acknowledger: Mapped["User"] = relationship(foreign_keys=[acknowledged_by])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LateEntryAck {self.entry_kind} {self.business_date}>"
