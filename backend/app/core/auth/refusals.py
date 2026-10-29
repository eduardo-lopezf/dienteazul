"""Why a session was refused — named, logged, and findable afterwards.

A 401 on ``/auth/refresh`` is the one answer a user always sees as "your
session is over", and until now it was the same opaque answer for seven
different causes: an undecodable token, a forged ``jti``, a spent one, a
revoked family, an inactive one, a bumped ``token_version``, a
deactivated account. The only one that left a trace was reuse. So an
incident — somebody thrown out mid-shift — could not be explained after
the fact, and the login screen guessed at the wording from a cookie the
browser had written itself.

Every refusal here carries the three things ADR 0059 promises:

- the **code**, so whoever debugs knows which of the cases it was;
- the **reference**, which the error handler fills in with the
  ``request_id`` this request already carries into every log line and
  into the operator's ``/ops/logs`` (ADR 0060) — the number the user
  reads off the login screen is what finds the line;
- the **category**, ``auth``, which is what sends the interface to
  login rather than showing a field error.

``refuse`` writes that log line itself, so a refusal cannot be raised
without leaving one. Facts are interpolated **unquoted**: the app log
scrubs quoted strings before an operator reads it (``server_errors.scrub``),
and a quoted ``jti`` would come back as ``'…'``.
"""

from __future__ import annotations

import logging

from fastapi import status

from app.core.errors import AppError

logger = logging.getLogger(__name__)

#: Refusals of ``POST /auth/refresh`` — the exchange itself failed.
REFRESH_UNDECODABLE = "auth.refresh.undecodable"
REFRESH_MALFORMED = "auth.refresh.malformed"
REFRESH_UNKNOWN = "auth.refresh.unknown"
REFRESH_REUSED = "auth.refresh.reused"
REFRESH_FAMILY_REVOKED = "auth.refresh.family_revoked"
REFRESH_FAMILY_INACTIVE = "auth.refresh.family_inactive"
REFRESH_VERSION_REVOKED = "auth.refresh.version_revoked"
REFRESH_USER_INACTIVE = "auth.refresh.user_inactive"

#: Refusals of an authenticated request — the access token was fine and
#: the session behind it was not.
SESSION_FAMILY_INACTIVE = "auth.session.family_inactive"
SESSION_FAMILY_UNKNOWN = "auth.session.family_unknown"

#: Refusals of ``POST /auth/activity``.
ACTIVITY_NO_FAMILY = "auth.activity.no_family"
ACTIVITY_FAMILY_INACTIVE = "auth.activity.family_inactive"

# --------------------------------------------------------------------------
# What the person is told
#
# Every code belongs to exactly one of these three groups, and
# ``tests/test_session_refusal_contract.py`` fails on a code that belongs
# to none or to two. That is the point of writing them down: the group
# decides the sentence on the login screen, and a new code that nobody
# classified would quietly inherit "your session expired" — which is the
# wrong sentence often enough that it is what this whole design exists to
# stop (ADR 0062).
# --------------------------------------------------------------------------

#: "Nobody was there." Waiting caused it, and the browser's own stamp
#: agrees often enough that the user recognises the answer.
IDLE_CODES: frozenset[str] = frozenset(
    {REFRESH_FAMILY_INACTIVE, SESSION_FAMILY_INACTIVE, ACTIVITY_FAMILY_INACTIVE}
)

#: "It was taken away": signed out elsewhere, revoked account-wide, or a
#: token presented twice. Not something waiting will fix, so it must not
#: read as a timeout.
REVOKED_CODES: frozenset[str] = frozenset(
    {
        REFRESH_REUSED,
        REFRESH_FAMILY_REVOKED,
        REFRESH_VERSION_REVOKED,
        REFRESH_USER_INACTIVE,
        SESSION_FAMILY_UNKNOWN,
    }
)

#: Everything else: the credential itself did not hold up. The only group
#: that may mean a defect, which is why it is the one an operator looks at
#: first when it appears without the other two.
EXPIRED_CODES: frozenset[str] = frozenset(
    {REFRESH_UNDECODABLE, REFRESH_MALFORMED, REFRESH_UNKNOWN, ACTIVITY_NO_FAMILY}
)


def refuse(code: str, detail: str, **facts: object) -> AppError:
    """A 401 that names its case, after logging it under this request.

    ``facts`` are the ids that make the line worth having — ``user``,
    ``family``, ``jti``, ``idle_minutes``. They are formatted
    ``name=value`` and must not be quoted; see this module's docstring.
    """
    trail = " ".join(f"{name}={value}" for name, value in facts.items())
    logger.warning("Session refused: code=%s%s", code, f" {trail}" if trail else "")
    return AppError(code, status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
