"""The subscription: its token, and what it publishes.

The user pastes one URL into Google Calendar, Apple Calendar or Outlook
and their agenda appears there. No OAuth, no Google Cloud project and no
verified domain — the client polls a URL and the only credential is the
token in it (ADR 0061).

Scope follows who the user *is* in this clinic: a professional publishes
their own appointments, anybody else — reception, administration, or a
clinic with the Professionals App off — publishes the clinic's. Both
questions belong to contracts, never to an import (ADR 0039).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AppointmentEntry

from .integrations import appointments, professionals
from .models import CalendarFeed

#: How much of the agenda the feed carries. The past is what makes the
#: calendar a record rather than a to-do list; the forward window is
#: wide enough for a treatment plan and narrow enough that the document
#: stays a few tens of kilobytes.
PAST_WINDOW = timedelta(days=30)
FUTURE_WINDOW = timedelta(days=180)


class CalendarFeedService:
    """A user's subscription URL, and the appointments behind it."""

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, user_id: UUID) -> CalendarFeed | None:
        """The user's feed in this clinic, or ``None`` if they have none."""
        result = await db.execute(
            select(CalendarFeed).where(
                CalendarFeed.clinic_id == clinic_id,
                CalendarFeed.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def issue(db: AsyncSession, clinic_id: UUID, user_id: UUID) -> CalendarFeed:
        """Create the feed, or replace its token.

        Rotation *is* revocation: the URLs already pasted into a phone
        stop resolving, which is the point — a URL that leaked is only
        recoverable by making it a 404.
        """
        feed = await CalendarFeedService.get(db, clinic_id, user_id)
        if feed is None:
            feed = CalendarFeed(clinic_id=clinic_id, user_id=user_id, token=uuid4())
            db.add(feed)
            await db.flush()
            return feed
        feed.token = uuid4()
        feed.last_access_at = None
        await db.flush()
        return feed

    @staticmethod
    async def revoke(db: AsyncSession, clinic_id: UUID, user_id: UUID) -> bool:
        """Delete the feed. ``False`` when there was none to delete."""
        feed = await CalendarFeedService.get(db, clinic_id, user_id)
        if feed is None:
            return False
        await db.delete(feed)
        await db.flush()
        return True

    @staticmethod
    async def resolve(db: AsyncSession, token: UUID) -> CalendarFeed | None:
        """The feed a public token names, if any."""
        result = await db.execute(select(CalendarFeed).where(CalendarFeed.token == token))
        return result.scalar_one_or_none()

    @staticmethod
    async def scope(db: AsyncSession, clinic_id: UUID, user_id: UUID) -> UUID | None:
        """The professional whose appointments the feed carries.

        ``None`` means the whole clinic: the user is not a professional
        here, or the Professionals App is off.
        """
        directory = professionals()
        if directory is None:
            return None
        return await directory.for_account(db, clinic_id, user_id)

    @staticmethod
    async def entries(
        db: AsyncSession,
        clinic_id: UUID,
        professional_id: UUID | None,
        *,
        now: datetime | None = None,
    ) -> list[AppointmentEntry]:
        """The window of appointments the feed publishes.

        Empty when the Agenda App is off: there is nothing to publish,
        and an empty calendar is the honest answer to a client that
        cannot be told anything else.
        """
        book = appointments()
        if book is None:
            return []
        reference = now or datetime.now(UTC)
        return await book.window(
            db,
            clinic_id,
            since=reference - PAST_WINDOW,
            until=reference + FUTURE_WINDOW,
            professional_id=professional_id,
        )
