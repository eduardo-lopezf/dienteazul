"""The record that a subject request happened.

An erasure is irreversible and leaves the data looking as if it had never
been there. Without a row saying who asked for it, when, and why, the
clinic cannot prove it honoured a request — and cannot tell an erasure
apart from a bug that emptied the columns.

The record deliberately holds **no personal data of its own** beyond the
patient id it acted on: the sections and counts describe what was done,
not what the data said. So it survives the erasure it documents.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.database import Base

ACTIONS = ("export", "erasure")


class SubjectRequest(Base):
    """One exercised subject right, and its outcome."""

    __tablename__ = "core_subject_request"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    # No FK: the patient row is archived rather than deleted, but an id
    # kept here must outlive whatever happens to the row it points at.
    patient_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)

    action: Mapped[str] = mapped_column(String(20))
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    # Who asked and on what grounds, in the operator's own words. Free
    # text on purpose: a dropdown would invite clicking through it.
    reason: Mapped[str] = mapped_column(Text)

    # What the fan-out did, section by section: rows scrubbed per
    # section, and the sections that refused with their stated reason.
    # Enough to reconstruct the answer given to the patient.
    outcome: Mapped[dict] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
