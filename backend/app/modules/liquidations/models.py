"""Liquidations module database models."""

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User
    from app.modules.professionals.models import Professional


# What the percentage is taken on. The two are different numbers and the
# gap between them is usually months wide on a big case, so which one a
# clinic pays on is an arrangement, not a detail.
#
# - ``collected``: the patient has actually paid for that work. The norm in
#   Mexico, and the default here — the clinic is never paying out money it
#   has not received.
# - ``earned``: the work was performed, paid or not. The associate carries
#   none of the collection risk, which some clinics offer and most do not.
COMMISSION_BASES = ["collected", "earned"]

# How the settlement was handed over. Only `cash` touches the till — a
# transfer reaches the associate's bank without the drawer ever opening, and
# writing a movement for it would make the next arqueo come up short by the
# whole payout.
PAYMENT_METHODS = ["cash", "transfer", "other"]


class ProfessionalCommission(Base, TimestampMixin):
    """What the clinic has agreed to pay one professional, and on what.

    Mutable on purpose: an arrangement that changes in March should not
    need a new row, and an old liquidation does not drift when it does
    because **the liquidation stores the percentage it used**. Same
    principle as the arqueo in `cashbox`: the document is the record, the
    setting is only what the next one starts from.

    One percentage per professional in this version. Clinics that split by
    discipline — 40 % on orthodontics, 50 % on surgery — are a real thing
    and the extension point is a child table keyed on the catalog category;
    nothing here has to change for it.
    """

    __tablename__ = "professional_commissions"
    __table_args__ = (
        UniqueConstraint("clinic_id", "professional_id", name="uq_professional_commission"),
        CheckConstraint("percent >= 0 AND percent <= 100", name="ck_commission_percent_range"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    # FK allowed: `professionals` is in `manifest.depends`.
    professional_id: Mapped[UUID] = mapped_column(
        ForeignKey("professionals.id", ondelete="CASCADE"), index=True
    )

    basis: Mapped[str] = mapped_column(String(10), default="collected")
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])
    professional: Mapped["Professional"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ProfessionalCommission {self.percent}% on {self.basis}>"


class Liquidation(Base, TimestampMixin):
    """One settlement with one professional for one period.

    Issued, not computed on read. A preview recalculates every time and
    that is right while nobody has been paid; the moment somebody is handed
    a figure, the figure has to stop moving — a patient paying tomorrow for
    work done last fortnight would otherwise change what was already
    settled.

    So `lines` is a frozen snapshot rather than a foreign key into the
    ledger, `percent` and `basis` are copied in beside it, and re-reading an
    issued liquidation in a year gives the same numbers the associate was
    paid on.
    """

    __tablename__ = "liquidations"
    __table_args__ = (
        CheckConstraint("percent >= 0 AND percent <= 100", name="ck_liquidation_percent_range"),
        CheckConstraint("date_to >= date_from", name="ck_liquidation_period"),
        Index("idx_liquidation_clinic_period", "clinic_id", "date_from", "date_to"),
        Index("idx_liquidation_professional", "clinic_id", "professional_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    professional_id: Mapped[UUID] = mapped_column(
        ForeignKey("professionals.id", ondelete="RESTRICT"), index=True
    )

    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)

    currency: Mapped[str] = mapped_column(String(3))
    # Snapshots of the arrangement as it stood when this was issued.
    basis: Mapped[str] = mapped_column(String(10))
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    # Both axes, always. Paying on one without seeing the other is how a
    # clinic ends up owing an associate money it has not been paid.
    earned_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    collected_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    #: Whichever of the two `basis` names — what the percentage was taken on.
    base_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount_due: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    #: The per-treatment detail exactly as it was settled.
    lines: Mapped[list] = mapped_column(JSONB, default=list)

    notes: Mapped[str | None] = mapped_column(Text, default=None)

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    issued_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    # --- Handing the money over -------------------------------------
    #
    # Recorded on the same row rather than in a table of its own: a
    # settlement is paid once, and "issued but not yet paid" is a state of
    # this document, not an event with a life of its own. It does not
    # contradict the freeze above — the settled figures never move; what is
    # added here is a later fact about them.
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    paid_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), default=None)
    #: cash | transfer | other. Only `cash` empties the drawer.
    payment_method: Mapped[str | None] = mapped_column(String(10), default=None)
    #: The till movement this payout wrote, when it was paid in cash.
    #: Cross-module FK, allowed because `cashbox` is in `manifest.depends`.
    cash_movement_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cash_movements.id", ondelete="RESTRICT"), default=None
    )

    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])
    professional: Mapped["Professional"] = relationship()
    issuer: Mapped["User"] = relationship(foreign_keys=[issued_by])
    payer: Mapped["User | None"] = relationship(foreign_keys=[paid_by])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Liquidation {self.date_from}..{self.date_to} {self.amount_due}>"
