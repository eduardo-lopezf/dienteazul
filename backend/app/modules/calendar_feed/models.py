"""The subscription itself: one URL per user per clinic."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.database import Base, TimestampMixin


class CalendarFeed(Base, TimestampMixin):
    """One user's agenda, published as an iCalendar URL.

    The token in the URL is the whole credential: Google Calendar, Apple
    Calendar and Outlook poll a feed unattended, so there is nobody to
    ask for a second factor the way the public budget link does
    (ADR 0061 vs ADR 0006). It is therefore a ``uuid4`` — unguessable by
    construction — and never a ``uuid7``, whose timestamp prefix is
    readable (ADR 0056).

    One feed per user per clinic: somebody working in two clinics
    subscribes to two URLs and revokes each on its own. No patient data
    is stored here — the document is built on request from whatever the
    agenda answers at that moment.
    """

    __tablename__ = "calendar_feeds"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(
        ForeignKey("clinics.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[UUID] = mapped_column(UUID(as_uuid=True), default=uuid4, unique=True, index=True)
    #: When a calendar client last fetched this feed. The one answer to
    #: "is my subscription working?", which is otherwise invisible: the
    #: clients poll on their own schedule and report nothing back.
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("uq_calendar_feed_clinic_user", "clinic_id", "user_id", unique=True),)
