"""An operator's notice to clinics."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.database import Base, TimestampMixin

KINDS = ("maintenance", "feature")


class Announcement(Base, TimestampMixin):
    """A short message shown beside the clinic's name at the top of the
    workspace while ``starts_at <= now < ends_at`` — to every clinic, or to
    the ones in ``clinic_ids``. Nothing personal: it is the operator's."""

    __tablename__ = "announcements"
    __table_args__ = (
        CheckConstraint("kind IN ('maintenance', 'feature')", name="ck_announcements_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    #: ``maintenance`` (a window when the system may be unavailable) or
    #: ``feature`` (something new to try).
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(String(280), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    #: ``None``: until it is taken down.
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The clinics it is for, as strings; ``None`` is every clinic.
    clinic_ids: Mapped[list[str] | None] = mapped_column(JSONB)
