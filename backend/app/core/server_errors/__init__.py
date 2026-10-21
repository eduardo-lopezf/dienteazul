"""The requests that ended in a server error, kept for the operator.

An exception nothing handled becomes a ``500`` ("Error del servidor") for
whoever made the request. Its log line goes wherever the process writes;
this keeps a row per occurrence in the database the operator's control
panel reads (``GET /api/v1/ops/errors``, ADR 0049 rule 4), so the origin
of a failure can be found from the panel, in development and in
production alike.

What a row holds is **where** it failed, never what it was working on:
the route, the exception's type, its message with any values taken out,
and the chain of calls — file, line and function, no local variables —
plus the request, clinic and user identifiers (ADR 0049 rule 5). A
database error's message names the values that broke a constraint; those
are replaced before the row is written.

Kept thirty days. Recording never raises: a failure to record a failure
is logged and dropped.
"""

from __future__ import annotations

import logging
import re
import traceback
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from .models import ServerError

logger = logging.getLogger(__name__)

#: How long an occurrence is kept.
RETENTION = timedelta(days=30)
_MESSAGE_LIMIT = 1000
_FRAMES_LIMIT = 40


# What a message may quote that is somebody's: the parameters SQLAlchemy
# appends, the values PostgreSQL names in a constraint's DETAIL, e-mail
# addresses, quoted strings and long digit runs.
_SCRUBS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\[parameters: .*?\]", re.S), "[parameters: …]"),
    (re.compile(r"\(Background on this error at: [^)]*\)"), ""),
    (
        re.compile(r"\)=\((.*?)\)( already exists| is not present| is still referenced)?"),
        r")=(…)\2",
    ),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "…@…"),
    (re.compile(r"'[^']{3,}'"), "'…'"),
    (re.compile(r"\b\d{6,}\b"), "…"),
)


def scrub(message: str) -> str:
    """``message`` without the values it quoted."""
    for pattern, replacement in _SCRUBS:
        message = pattern.sub(replacement, message)
    return message.strip()[:_MESSAGE_LIMIT]


def frames_of(exc: BaseException) -> str:
    """The calls that led to ``exc``: where, never with what."""
    summary = traceback.extract_tb(exc.__traceback__)[-_FRAMES_LIMIT:]
    lines = [f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in summary]
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc:
        lines.append(f"caused by {type(cause).__module__}.{type(cause).__qualname__}")
    return "\n".join(lines)


async def record(
    exc: BaseException,
    *,
    method: str,
    path: str,
    request_id: str | None,
    clinic_id: str | None,
    user_id: str | None,
) -> None:
    """Keep one occurrence, in a session of its own: the request's own may
    be what failed. Never raises."""
    from app.database import async_session_maker

    try:
        async with async_session_maker() as db:
            now = datetime.now(UTC)
            db.add(
                ServerError(
                    occurred_at=now,
                    method=method[:10],
                    path=path[:300],
                    error_type=f"{type(exc).__module__}.{type(exc).__qualname__}"[:200],
                    message=scrub(str(exc)) or type(exc).__name__,
                    frames=frames_of(exc),
                    request_id=request_id,
                    clinic_id=clinic_id,
                    user_id=user_id,
                )
            )
            await db.execute(delete(ServerError).where(ServerError.occurred_at < now - RETENTION))
            await db.commit()
    except Exception:  # noqa: BLE001 — recording must never be the next failure
        logger.exception("Could not record a server error")
