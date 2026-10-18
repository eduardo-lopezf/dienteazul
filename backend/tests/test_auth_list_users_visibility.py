"""`GET /auth/users` shows this clinic's staff and nobody else's.

The listing used to return **every account in the deployment** — email,
name, sign-in state, created date — and that was deliberate. It rested on
one premise, written into the endpoint: "one clinic per deployment, so an
account outside this clinic is residue of the same installation rather
than another tenant's staff". Deployments hold several clinics, so the
premise was false and the screen was showing each tenant the others'
people.

The problem the global listing was built for is covered at the door
instead: `/auth/login` refuses an account with no membership anywhere
(`test_auth_account_access.py`), so "remove from the clinic" already
stops the login. An account that belongs to *another* clinic is that
clinic's business.

These tests are the ratchet. They fail if the listing ever widens again.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.core.auth.service import hash_password


async def _user(db: AsyncSession, email: str, first: str = "Someone") -> User:
    user = User(
        email=email,
        password_hash=hash_password("TestPass1234"),
        first_name=first,
        last_name="Elsewhere",
    )
    db.add(user)
    await db.commit()
    return user


async def _clinic(db: AsyncSession, name: str) -> Clinic:
    clinic = Clinic(
        id=uuid4(),
        name=name,
        tax_id=f"B{uuid4().int % 100000000:08d}",
        address={"street": "Elsewhere", "city": "Bilbao"},
        settings={},
        account_tier="clinic",
    )
    db.add(clinic)
    await db.commit()
    return clinic


def _emails(body: dict) -> set[str]:
    return {u["email"] for u in body["data"]}


@pytest.mark.asyncio
async def test_another_clinics_staff_are_not_listed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    db_session: AsyncSession,
) -> None:
    """The reported leak: one tenant reading another tenant's people."""
    theirs = await _user(db_session, f"theirs-{uuid4().hex[:8]}@example.com")
    other = await _clinic(db_session, "Another Tenant")
    db_session.add(ClinicMembership(user_id=theirs.id, clinic_id=other.id, role="admin"))
    await db_session.commit()

    response = await client.get("/api/v1/auth/users", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert theirs.email not in _emails(response.json())


@pytest.mark.asyncio
async def test_an_account_with_no_membership_is_not_listed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    db_session: AsyncSession,
) -> None:
    """It cannot sign in either, so there is nothing for an admin to do.

    This is the row the old listing existed to surface. Login refuses it
    now, which is where that belongs.
    """
    orphan = await _user(db_session, f"orphan-{uuid4().hex[:8]}@example.com")

    response = await client.get("/api/v1/auth/users", headers=auth_headers)

    assert orphan.email not in _emails(response.json())


@pytest.mark.asyncio
async def test_this_clinics_staff_are_listed_with_their_role(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    db_session: AsyncSession,
) -> None:
    """The positive control: scoping it to nothing would pass the rest."""
    ours = await _user(db_session, f"ours-{uuid4().hex[:8]}@example.com")
    db_session.add(ClinicMembership(user_id=ours.id, clinic_id=test_clinic.id, role="hygienist"))
    await db_session.commit()

    body = (await client.get("/api/v1/auth/users", headers=auth_headers)).json()

    listed = next((u for u in body["data"] if u["email"] == ours.email), None)
    assert listed is not None, "this clinic's own staff must appear"
    assert listed["role"] == "hygienist"


@pytest.mark.asyncio
async def test_someone_in_both_clinics_appears_once_with_the_role_here(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    db_session: AsyncSession,
) -> None:
    """A person may be staff in two clinics; each sees only its own half.

    The account is shared — one email, one login — so the isolation that
    matters is that the role shown is the one here, and that the other
    membership is not reported at all.
    """
    both = await _user(db_session, f"both-{uuid4().hex[:8]}@example.com")
    other = await _clinic(db_session, "Their Clinic")
    db_session.add_all(
        [
            ClinicMembership(user_id=both.id, clinic_id=test_clinic.id, role="assistant"),
            ClinicMembership(user_id=both.id, clinic_id=other.id, role="admin"),
        ]
    )
    await db_session.commit()

    body = (await client.get("/api/v1/auth/users", headers=auth_headers)).json()

    rows = [u for u in body["data"] if u["email"] == both.email]
    assert len(rows) == 1, "one person is one row"
    assert rows[0]["role"] == "assistant", "the role elsewhere must not leak"
