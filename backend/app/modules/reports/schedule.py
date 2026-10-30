"""The standing order for a clinic's one-page summary.

Two questions live here: *is this clinic due today* and *which period
does today's send cover*. Both are pure date arithmetic so they can be
tested without a scheduler, a mailbox or a clock.

**Why a send is not a patient notification.** The recipients are the
clinic's own people reading the clinic's own figures, so none of what
the notifications gateway exists to enforce — consent, `do_not_contact`,
per-patient preferences, the outbox audit — has anything to say about
it. The summary goes out through `app.core.email` from a scheduled job,
never from a request, which is the rule that gateway protects.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CADENCES, SummarySchedule


def clinic_today(timezone: str | None) -> date:
    """Today as the clinic lives it, not as the server does.

    A job that runs at 07:00 UTC is the previous evening in Mexico; using
    the server's date would send the "month just finished" summary a day
    early for half the clinics.
    """
    from datetime import datetime

    try:
        zone = ZoneInfo(timezone) if timezone else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date()


def period_due(cadence: str, today: date) -> tuple[date, date] | None:
    """The period today's send covers, or ``None`` when nothing is due.

    The summary goes out at the first moment a period's figures stop
    moving: Monday for the week just ended, the 1st for the month just
    ended. Any other day, there is nothing to send.
    """
    if cadence == "weekly" and today.weekday() == 0:  # Monday
        end = today - timedelta(days=1)
        return end - timedelta(days=6), end
    if cadence == "monthly" and today.day == 1:
        end = today - timedelta(days=1)
        return end.replace(day=1), end
    return None


async def get_or_create(db: AsyncSession, clinic_id: UUID) -> SummarySchedule:
    """The clinic's schedule, inert until somebody turns it on."""
    schedule = await db.get(SummarySchedule, clinic_id)
    if schedule is None:
        schedule = SummarySchedule(clinic_id=clinic_id)
        db.add(schedule)
        await db.flush()
    return schedule


async def update(
    db: AsyncSession,
    clinic_id: UUID,
    *,
    is_active: bool,
    cadence: str,
    recipients: list[str],
) -> SummarySchedule:
    schedule = await get_or_create(db, clinic_id)
    schedule.is_active = is_active
    schedule.cadence = cadence if cadence in CADENCES else "monthly"
    schedule.recipients = recipients
    await db.flush()
    return schedule


async def active_schedules(db: AsyncSession) -> list[SummarySchedule]:
    """Every clinic that asked for the summary, with somebody to send it to."""
    rows = (
        await db.execute(select(SummarySchedule).where(SummarySchedule.is_active.is_(True)))
    ).scalars()
    return [row for row in rows if row.recipients]


def already_sent(schedule: SummarySchedule, period_end: date) -> bool:
    """Whether this period already went out.

    The guard is the period, not the day: a job that runs twice — a
    restart, a second worker (ADR 0051) — must not mail the same summary
    twice, and a job that misses its day entirely should not send a
    period the clinic already has.
    """
    return schedule.last_sent_for is not None and schedule.last_sent_for >= period_end
