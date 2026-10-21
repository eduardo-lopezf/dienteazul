"""One request that ended in a server error (see the package)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.database import Base


class ServerError(Base):
    """One request that ended in an unhandled exception."""

    __tablename__ = "server_errors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    #: The route's template (``/api/v1/patients/{patient_id}``) when one
    #: matched — never the path with its identifiers — else the path.
    path: Mapped[str] = mapped_column(String(300), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    #: ``module.ClassName`` of the exception.
    error_type: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Its message, with the values it quoted replaced.
    message: Mapped[str] = mapped_column(Text, nullable=False)
    #: Where it was raised, innermost last: ``file:line in function``.
    frames: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    clinic_id: Mapped[str | None] = mapped_column(String(36))
    user_id: Mapped[str | None] = mapped_column(String(36))
