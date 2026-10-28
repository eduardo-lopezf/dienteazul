"""What the subscription looks like over HTTP."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class CalendarFeedResponse(BaseModel):
    """The caller's iCalendar subscription in this clinic.

    ``path`` and not a URL: the backend does not know the address it is
    reached at, and the frontend already does. ``scope`` says whose
    appointments the document carries — ``own`` for a professional,
    ``clinic`` for everybody else.
    """

    token: UUID
    path: str
    scope: Literal["own", "clinic"]
    last_access_at: datetime | None = None
    created_at: datetime
