"""A user's own account of something that did not work."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.database import Base, TimestampMixin

STATES = ("new", "read", "archived")

MAX_DESCRIPTION = 2000


class ErrorReport(Base, TimestampMixin):
    """One report written from the Help drawer ("Reportar un error").

    The companion of ``app.core.server_errors`` and
    ``app.core.client_errors``, and the opposite of both: those record
    what the machine saw, this records what the person saw. A screen that
    stays loading for ever raises no exception anywhere, so prose is the
    only witness there is.

    The description is free text, so it may name a patient even though it
    is not meant to: it is a staff member describing their afternoon. It
    is therefore never sent to a model, never exported with a patient's
    data, and read only through ``/api/v1/ops`` — the operator's console,
    which already carries that duty (ADR 0049 rule 5). The context beside
    it is bounded and impersonal: the route, the build, and who filed it.
    """

    __tablename__ = "error_reports"
    __table_args__ = (
        CheckConstraint("state IN ('new', 'read', 'archived')", name="ck_error_reports_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Who filed it, so the operator can write back. The row outlives the
    #: user only as far as the user does: deleting the user deletes it.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: What they wrote, in their own words.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    #: The route they were on, without its query string: that is where
    #: somebody's identifier would be.
    path: Mapped[str] = mapped_column(String(300), nullable=False)
    #: The build of the interface that showed the problem. Empty when the
    #: deployment does not state one.
    app_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    #: Where the operator has got to with it: ``new``, ``read``,
    #: ``archived``.
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)
