"""The public iCalendar document: one GET, no session.

``GET /api/v1/calendar_feed/calendar/{token}.ics`` is what Google
Calendar, Apple Calendar and Outlook poll after the user pastes the URL.
They poll unattended, so the token in the path is the whole credential —
there is nobody to ask for a second factor the way the public budget
link does (ADR 0061 vs ADR 0006).

What follows from that:

- **Anything that is not a live token is a bare 404.** No body, and no
  hint whether the token is malformed, revoked or never existed.
- **Rate limited per IP.** Guessing a 122-bit token is hopeless anyway;
  the limit is there so a misconfigured client cannot poll the agenda in
  a loop.
- **``X-Robots-Tag: noindex``** comes from the global security-headers
  middleware, so a leaked URL does not end up in an index.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.auth.router import limiter
from app.database import get_db

from . import ics
from .service import CalendarFeedService

public_router = APIRouter()


@public_router.get("/calendar/{token}.ics", include_in_schema=False)
@limiter.limit("120/hour")
async def calendar_document(
    request: Request,
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Serve one user's agenda as an iCalendar document."""
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    try:
        parsed = UUID(token)
    except ValueError:
        raise not_found from None

    feed = await CalendarFeedService.resolve(db, parsed)
    if feed is None:
        raise not_found

    clinic = (
        await db.execute(select(Clinic).where(Clinic.id == feed.clinic_id))
    ).scalar_one_or_none()
    if clinic is None:
        raise not_found

    professional_id = await CalendarFeedService.scope(db, feed.clinic_id, feed.user_id)
    entries = await CalendarFeedService.entries(db, feed.clinic_id, professional_id)

    # The one signal the user has that their subscription is alive.
    # ``commit_before_response`` persists it (ADR 0031).
    feed.last_access_at = datetime.now(UTC)

    document = ics.render(entries, calendar_name=clinic.name, timezone=clinic.timezone)
    return Response(
        content=document,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="dienteazul.ics"',
            "Cache-Control": "private, max-age=600",
        },
    )
