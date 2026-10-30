"""What this module stores: when to send the clinic its own summary.

The reports are computed on demand from other modules' tables, so this
is the only row the module owns — a schedule, one per clinic, lazily
created the first time somebody opens the setting.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.privacy.classification import PiiKind, pii
from app.database import Base

#: How often the summary goes out. Weekly lands on Monday for the week
#: just finished; monthly on the 1st for the month just finished — both
#: are the first working moment after a period closes, which is when the
#: figures stop moving.
CADENCES = ("weekly", "monthly")


class SummarySchedule(Base):
    """One clinic's standing order for its one-page summary.

    ``recipients`` are the clinic's own people, not patients: no consent
    gate applies and the notifications outbox (which exists to protect
    patients) is not involved. They are still personal data, hence the
    classification.
    """

    __tablename__ = "reports_summary_schedule"

    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), primary_key=True
    )
    #: Off by default: nothing leaves a clinic until somebody asks it to.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cadence: Mapped[str] = mapped_column(String(10), nullable=False, default="monthly")
    #: Staff e-mail addresses, in the order they were entered.
    recipients: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        info=pii(PiiKind.EMAIL),
    )
    #: The period end the last successful send covered. Both the "has it
    #: already gone out" guard and the answer to "when did I last get it".
    last_sent_for: Mapped[date | None] = mapped_column(Date, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MonthlyTarget(Base):
    """What a clinic said it wanted from one month.

    Set by hand, one row per month, and every column nullable: a clinic
    that only cares about collection should not have to invent a goal for
    new patients. ``None`` means "no goal", which a screen draws
    differently from a goal of zero.
    """

    __tablename__ = "reports_monthly_target"

    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id"), primary_key=True
    )
    #: Always the first of the month; the month is the grain.
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    collected_target: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    production_target: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    new_patients_target: Mapped[int | None] = mapped_column(Integer, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
