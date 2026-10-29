"""A session can be ended, and a stolen refresh token gets caught.

ADR 0029, invariant 3. Before ``auth_sessions`` the only revocation was
``User.token_version`` — a global switch, incremented in one place, that
logs a user out of every device at once. These are the three behaviours
that replace it: rotation, reuse detection, and a logout that reaches
the server.

The tests drive the HTTP endpoints rather than the service, because the
defect being fixed was in the endpoints: the service could have been
perfect and `/auth/logout` still would not have existed.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import refusals, sessions
from app.core.auth.models import AuthSession, Clinic, ClinicMembership, User
from app.core.auth.service import create_refresh_token, decode_token, hash_password

PASSWORD = "TestPass1234"


async def _make_user(db: AsyncSession, email: str) -> User:
    """A user who can sign in — which now means one with a clinic.

    ``/auth/login`` refuses an account with no membership: removing
    someone from a clinic has to take their sign-in with it. These tests
    are about what happens *after* a login, so each probe gets a clinic
    of its own rather than a shared one, and nothing here depends on
    another test's fixtures.
    """
    user = User(
        email=email,
        password_hash=hash_password(PASSWORD),
        first_name="Session",
        last_name="Probe",
    )
    clinic = Clinic(
        name=f"Clinic for {email}",
        tax_id="A28000000",
        timezone="Europe/Madrid",
        currency="EUR",
        settings={},
        account_tier="clinic",
    )
    db.add_all([user, clinic])
    await db.flush()
    db.add(ClinicMembership(user_id=user.id, clinic_id=clinic.id, role="admin"))
    await db.commit()
    return user


async def _login(client: AsyncClient, email: str) -> tuple[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["access_token"], body["refresh_token"]


async def _refresh(client: AsyncClient, token: str):
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": token})


@pytest.mark.asyncio
async def test_refresh_rotates_and_spends_the_old_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, "rotate@example.com")
    _, first = await _login(client, user.email)

    response = await _refresh(client, first)

    assert response.status_code == 200, response.text
    second = response.json()["refresh_token"]
    assert second != first, "the refresh token was reissued unchanged"

    # And the successor works, so rotation is not a one-way trip.
    assert (await _refresh(client, second)).status_code == 200


@pytest.mark.asyncio
async def test_reusing_a_spent_token_kills_the_whole_family(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The case the design exists for.

    A refresh token is a bearer credential: a stolen one is
    indistinguishable from the real one *until it is used twice*. At that
    point there are two holders and no way to tell which is the thief, so
    both lose — refusing only the second presentation would leave the
    attacker holding a working chain.
    """
    user = await _make_user(db_session, "reuse@example.com")
    _, stolen = await _login(client, user.email)

    # The legitimate holder refreshes; `stolen` is now spent.
    live = (await _refresh(client, stolen)).json()["refresh_token"]

    replay = await _refresh(client, stolen)

    assert replay.status_code == 401

    # The thief is out — and so is the victim, which is the trade.
    assert (await _refresh(client, live)).status_code == 401
    assert await sessions.usable_sessions(db_session, user.id) == []


@pytest.mark.asyncio
async def test_logout_ends_the_session_server_side(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """What `useAuth.logout()` could not do: reach the server.

    Clearing the cookie left the refresh token valid for its full seven
    days.
    """
    user = await _make_user(db_session, "logout@example.com")
    _, refresh = await _login(client, user.email)

    response = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})

    assert response.status_code == 204
    assert (await _refresh(client, refresh)).status_code == 401
    assert await sessions.usable_sessions(db_session, user.id) == []


@pytest.mark.asyncio
async def test_logout_is_silent_about_tokens_it_does_not_know(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An endpoint that reports which tokens exist is an oracle."""
    user = await _make_user(db_session, "quiet@example.com")

    garbage = await client.post("/api/v1/auth/logout", json={"refresh_token": "not-a-jwt"})
    orphan = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": create_refresh_token(user.id, jti=user.id)},
    )

    assert garbage.status_code == 204
    assert orphan.status_code == 204


@pytest.mark.asyncio
async def test_a_refresh_token_naming_no_session_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Tokens minted before this table named no row, so nothing could revoke them.

    Rejecting them logs those holders out once, which is the point.
    """
    user = await _make_user(db_session, "legacy@example.com")
    legacy = create_refresh_token(user.id, token_version=user.token_version)

    assert (await _refresh(client, legacy)).status_code == 401


@pytest.mark.asyncio
async def test_logging_out_one_device_leaves_the_other_alone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The whole reason this is not `token_version`.

    Two logins are two families. Ending one must not end the other —
    that is exactly what the global switch could not do.
    """
    user = await _make_user(db_session, "twodevices@example.com")
    _, laptop = await _login(client, user.email)
    _, phone = await _login(client, user.email)

    await client.post("/api/v1/auth/logout", json={"refresh_token": laptop})

    assert (await _refresh(client, laptop)).status_code == 401
    assert (await _refresh(client, phone)).status_code == 200


@pytest.mark.asyncio
async def test_family_deadline_is_fixed_and_refresh_exp_is_clamped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, "deadline@example.com")
    access, first = await _login(client, user.email)
    access_payload = decode_token(access)
    first_payload = decode_token(first)
    session = await db_session.get(AuthSession, first_payload["jti"])
    assert session is not None
    assert access_payload["family_id"] == str(session.family_id)

    deadline = datetime.now(UTC) + timedelta(days=2)
    await db_session.execute(
        update(AuthSession)
        .where(AuthSession.family_id == session.family_id)
        .values(family_expires_at=deadline)
    )
    await db_session.commit()

    response = await _refresh(client, first)
    assert response.status_code == 200, response.text
    successor_payload = decode_token(response.json()["refresh_token"])
    successor = await db_session.get(AuthSession, successor_payload["jti"])
    assert successor is not None
    assert successor.family_id == session.family_id
    assert successor.family_expires_at == deadline
    assert successor.last_activity_at == session.last_activity_at
    assert successor.expires_at == deadline
    assert successor_payload["exp"] == int(deadline.timestamp())


@pytest.mark.asyncio
async def test_absolute_expiry_rejects_refresh_without_reuse_revocation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, "absolute-expiry@example.com")
    _, refresh = await _login(client, user.email)
    payload = decode_token(refresh)
    session = await db_session.get(AuthSession, payload["jti"])
    assert session is not None
    await db_session.execute(
        update(AuthSession)
        .where(AuthSession.family_id == session.family_id)
        .values(family_expires_at=session.created_at)
    )
    await db_session.commit()

    response = await _refresh(client, refresh)

    assert response.status_code == 401
    await db_session.refresh(session)
    assert session.revoked_at is None
    assert session.revoked_reason is None


@pytest.mark.asyncio
async def test_idle_policy_rejects_refresh_and_access(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, "idle-expiry@example.com")
    access, refresh = await _login(client, user.email)
    payload = decode_token(refresh)
    session = await db_session.get(AuthSession, payload["jti"])
    assert session is not None
    await db_session.execute(
        update(AuthSession)
        .where(AuthSession.family_id == session.family_id)
        .values(last_activity_at=datetime.now(UTC) - timedelta(hours=2))
    )
    await db_session.commit()

    refused = await _refresh(client, refresh)
    assert refused.status_code == 401
    # The case, not just the status: the login screen says "inactividad"
    # off this code and an operator finds the line by the reference
    # (ADR 0062).
    assert refused.json()["code"] == refusals.REFRESH_FAMILY_INACTIVE
    assert refused.json()["reference"]
    access_response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert access_response.status_code == 401
    assert access_response.json()["code"] == refusals.SESSION_FAMILY_INACTIVE
    await db_session.refresh(session)
    assert session.revoked_reason is None


@pytest.mark.asyncio
async def test_every_way_a_session_is_refused_names_its_case(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """One 401 per cause, each saying which cause it was.

    They were one indistinguishable answer, and only reuse left a trace —
    so somebody thrown out mid-shift could not be told, or found in the
    log, which of seven things had happened (ADR 0062).
    """
    user = await _make_user(db_session, "refusal-codes@example.com")
    access, refresh = await _login(client, user.email)

    # Undecodable, and a well-formed token that names no session row.
    assert (await _refresh(client, "not-a-token")).json()["code"] == refusals.REFRESH_UNDECODABLE
    orphan = create_refresh_token(user.id, jti=uuid4())
    assert (await _refresh(client, orphan)).json()["code"] == refusals.REFRESH_UNKNOWN

    # An access token presented where a refresh one belongs.
    assert (await _refresh(client, access)).json()["code"] == refusals.REFRESH_MALFORMED

    # The account-wide switch: every token minted before it is refused.
    user.token_version += 1
    await db_session.commit()
    assert (await _refresh(client, refresh)).json()["code"] == refusals.REFRESH_VERSION_REVOKED

    # And a family that was revoked under a live access token.
    other = await _make_user(db_session, "refusal-codes-revoked@example.com")
    other_access, other_refresh = await _login(client, other.email)
    payload = decode_token(other_refresh)
    revoked = await db_session.get(AuthSession, payload["jti"])
    assert revoked is not None
    await sessions.revoke_family(db_session, revoked.family_id, "logout")
    await db_session.commit()
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {other_access}"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == refusals.SESSION_FAMILY_UNKNOWN


@pytest.mark.asyncio
async def test_reuse_is_refused_by_name(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "reuse-code@example.com")
    _, refresh = await _login(client, user.email)
    assert (await _refresh(client, refresh)).status_code == 200

    replayed = await _refresh(client, refresh)

    assert replayed.status_code == 401
    assert replayed.json()["code"] == refusals.REFRESH_REUSED


@pytest.mark.asyncio
async def test_activity_extends_idle_without_moving_family_deadline(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, "activity@example.com")
    access, refresh = await _login(client, user.email)
    payload = decode_token(refresh)
    session = await db_session.get(AuthSession, payload["jti"])
    assert session is not None
    deadline = session.family_expires_at
    await db_session.execute(
        update(AuthSession)
        .where(AuthSession.family_id == session.family_id)
        .values(last_activity_at=datetime.now(UTC) - timedelta(minutes=30))
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/activity", headers={"Authorization": f"Bearer {access}"}
    )
    assert response.status_code == 204, response.text
    await db_session.refresh(session)
    assert session.last_activity_at > session.created_at
    assert session.family_expires_at == deadline
    rotated = await _refresh(client, refresh)
    assert rotated.status_code == 200, rotated.text
    successor = await db_session.get(
        AuthSession, decode_token(rotated.json()["refresh_token"])["jti"]
    )
    assert successor is not None
    assert successor.family_expires_at == deadline


@pytest.mark.asyncio
async def test_parallel_refresh_has_at_most_one_successor(
    db_session: AsyncSession,
) -> None:
    """PostgreSQL row locking serializes concurrent spends of one jti."""
    from app.database import async_session_maker

    user = await _make_user(db_session, "parallel@example.com")
    original = await sessions.start_session(db_session, user.id)
    await db_session.commit()

    async def rotate_once() -> str:
        async with async_session_maker() as db:
            try:
                await sessions.rotate(db, original.id)
            except sessions.RefreshReuseError:
                await db.commit()
                return "reuse"
            await db.commit()
            return "rotated"

    outcomes = await asyncio.gather(rotate_once(), rotate_once())

    assert outcomes.count("rotated") == 1
    assert outcomes.count("reuse") == 1
    assert await sessions.usable_sessions(db_session, user.id) == []
