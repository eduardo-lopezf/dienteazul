"""Refresh-token sessions: rotation, reuse detection, revocation.

ADR 0029, invariant 3. The rules this file implements, in one place
because they only make sense together:

1. **A refresh token is spent when it is used.** Every exchange stamps
   ``rotated_at`` on the presented row and issues a new one. A refresh
   token therefore has exactly one legitimate use.

2. **Reuse means theft, and we cannot tell whose.** A bearer credential
   presented twice has two holders. Which one is the attacker is not
   knowable from the request, so the whole family is revoked and both
   have to authenticate again. Refusing only the second presentation
   would leave the thief holding a working chain.

3. **Logout ends the family, not the row.** Ending only the presented
   token would leave its already-issued successors alive, which is not
   what anyone means by logging out.

``User.token_version`` is untouched and still works: it stays the
per-user emergency switch that invalidates *access* tokens too, which
this table cannot do — an access token is stateless by design and lives
15 minutes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from .models import AuthSession


class RefreshReuseError(Exception):
    """A spent or revoked refresh token was presented again.

    Separate from "unknown token" on purpose: the caller answers both
    with 401, but only this one means a live session family was just
    destroyed, and only this one is worth a log line an operator can act
    on.
    """


class RevokedFamilyError(Exception):
    """The family this token belongs to was already revoked.

    Told apart from :class:`RefreshReuseError` because the two mean
    opposite things to whoever reads the log. A token presented after its
    family was ended — the ordinary case being a refresh in flight when
    somebody signed out, or a second tab catching up — used to be
    answered as reuse: it re-revoked a family that was already dead and
    logged "reuse detected", which reads as theft. Reuse is a token that
    was *spent* and came back; that is still what this file treats as
    theft (ADR 0062).
    """

    def __init__(self, family_id: UUID, reason: str | None) -> None:
        super().__init__(f"session family {family_id} was revoked ({reason or 'unknown'})")
        self.family_id = family_id
        #: Why it was revoked, as ``revoke_family`` recorded it.
        self.reason = reason


class InactiveFamilyError(Exception):
    """The session family exceeded its absolute or idle lifetime.

    Carries which of the two it was and how long the family had gone
    unextended: the caller turns both into the log line that explains an
    incident, and "idle for 61 minutes" and "idle for nine hours" are
    the same 401 with very different causes (ADR 0062).
    """

    def __init__(self, family_id: UUID, *, idle_minutes: int, absolute: bool) -> None:
        super().__init__(
            f"session family {family_id} is inactive "
            f"(idle {idle_minutes} min, absolute deadline passed: {absolute})"
        )
        self.family_id = family_id
        #: Whole minutes since ``last_activity_at``.
        self.idle_minutes = idle_minutes
        #: ``True`` when it was the 30-day family deadline, not the idle window.
        self.absolute = absolute


async def start_session(db: AsyncSession, user_id: UUID) -> AuthSession:
    """Open a new family. Called on login and on first-run setup."""
    family_id = uuid4()
    now = datetime.now(UTC)
    family_expires_at = now + timedelta(days=settings.AUTH_SESSION_MAX_FAMILY_DAYS)
    session = AuthSession(
        id=uuid4(),
        user_id=user_id,
        family_id=family_id,
        expires_at=min(now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), family_expires_at),
        family_expires_at=family_expires_at,
        last_activity_at=now,
    )
    db.add(session)
    return session


async def revoke_family(db: AsyncSession, family_id: UUID, reason: str) -> int:
    """Kill every row in a family. Returns how many were still usable."""
    result = await db.execute(
        update(AuthSession)
        .where(
            AuthSession.family_id == family_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
    )
    return result.rowcount or 0


async def rotate(db: AsyncSession, jti: UUID) -> AuthSession:
    """Spend the token named by ``jti`` and open its successor.

    Raises :class:`RefreshReuseError` when the token was already spent or
    revoked — and revokes the family before raising, because the caller
    must not be able to forget to.

    Raises :class:`LookupError` when no such row exists: an unknown
    ``jti`` is a forged or long-purged token, and there is no family to
    punish for it.
    """
    result = await db.execute(
        select(AuthSession)
        .where(AuthSession.id == jti)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise LookupError(f"no session for jti {jti}")

    now = datetime.now(UTC)
    absolute = session.family_expires_at <= now
    idle = (
        session.last_activity_at + timedelta(minutes=settings.AUTH_SESSION_IDLE_TIMEOUT_MINUTES)
        <= now
    )
    if absolute or idle:
        raise InactiveFamilyError(
            session.family_id,
            idle_minutes=int((now - session.last_activity_at).total_seconds() // 60),
            absolute=absolute,
        )

    if session.revoked_at is not None:
        raise RevokedFamilyError(session.family_id, session.revoked_reason)

    if not session.is_usable:
        await revoke_family(db, session.family_id, "reuse")
        raise RefreshReuseError(f"refresh token {jti} was already spent")

    if session.expires_at <= now:
        raise LookupError(f"session {jti} expired")

    session.rotated_at = now
    successor = AuthSession(
        id=uuid4(),
        user_id=session.user_id,
        family_id=session.family_id,
        expires_at=min(
            now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), session.family_expires_at
        ),
        family_expires_at=session.family_expires_at,
        last_activity_at=session.last_activity_at,
    )
    db.add(successor)
    return successor


async def record_activity(db: AsyncSession, family_id: UUID, user_id: UUID) -> bool:
    """Extend the idle window for every still-unrevoked row in a family."""
    now = datetime.now(UTC)
    result = await db.execute(
        update(AuthSession)
        .where(
            AuthSession.family_id == family_id,
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.family_expires_at > now,
            AuthSession.last_activity_at
            > now - timedelta(minutes=settings.AUTH_SESSION_IDLE_TIMEOUT_MINUTES),
        )
        .values(last_activity_at=now)
    )
    return bool(result.rowcount)


async def end_session(db: AsyncSession, jti: UUID) -> bool:
    """Log out: revoke the family the token belongs to.

    Returns False for an unknown ``jti`` so the caller can stay quiet
    about it — a logout that reports whether a token was real is an
    oracle, and logging out is not an operation worth failing.
    """
    session = await db.get(AuthSession, jti)
    if session is None:
        return False

    await revoke_family(db, session.family_id, "logout")
    return True


async def usable_sessions(db: AsyncSession, user_id: UUID) -> list[AuthSession]:
    """Sessions a user could still refresh with. For tests and, later, a UI."""
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.rotated_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    return list(result.scalars().all())
