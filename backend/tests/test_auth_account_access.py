"""An account that belongs to no clinic cannot sign in.

`/auth/login` only ever asked for a password and an active flag, so an
account with no membership anywhere signed in happily and got a token
with `clinic_id = None` — able to do nothing, and invisible to the one
screen that could stop it. Accounts reach that state on their own:
`DELETE /auth/users/{id}` removes the membership and keeps the account,
so "remove from clinic" left a working login behind.

No membership, no sign-in — which also makes removing someone from the
clinic mean what it says.

This file used to have a second half, covering an admin's switch over
accounts belonging to *other* clinics. That switch is gone: it rested on
"one clinic per deployment", and deployments hold several, so it was one
tenant reaching into another's staff. The last test here is what stops it
coming back. Tenant-scoped listing is pinned in
`test_auth_list_users_visibility.py`.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.core.auth.service import hash_password

PASSWORD = "TestPass1234"


async def _user(db: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        password_hash=hash_password(PASSWORD),
        first_name="Left",
        last_name="Behind",
    )
    db.add(user)
    await db.commit()
    return user


async def _other_clinic(db: AsyncSession) -> Clinic:
    clinic = Clinic(
        id=uuid4(),
        name="Clinic From Before The Seed",
        tax_id=f"B{uuid4().int % 100000000:08d}",
        address={"street": "Elsewhere", "city": "Bilbao"},
        settings={},
        account_tier="clinic",
    )
    db.add(clinic)
    await db.commit()
    return clinic


async def _login(client: AsyncClient, email: str):
    return await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


# --- no membership, no sign-in ----------------------------------------


@pytest.mark.asyncio
async def test_an_account_with_no_membership_cannot_sign_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    orphan = await _user(db_session, f"orphan-{uuid4().hex[:8]}@example.com")

    response = await _login(client, orphan.email)

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_removing_someone_from_the_clinic_ends_their_sign_in(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    db_session: AsyncSession,
) -> None:
    """The reason the first rule matters.

    `DELETE /auth/users/{id}` drops the membership and keeps the account,
    so before this an admin who removed somebody left them a working login
    and no way to see it.
    """
    member = await _user(db_session, f"member-{uuid4().hex[:8]}@example.com")
    db_session.add(
        ClinicMembership(user_id=member.id, clinic_id=test_clinic.id, role="receptionist")
    )
    await db_session.commit()
    # Read off the instance before it is expired below: afterwards every
    # attribute is a lazy load, and a lazy load here is a `MissingGreenlet`.
    email, member_id = member.email, member.id
    assert (await _login(client, email)).status_code == 200

    removed = await client.delete(f"/api/v1/auth/users/{member_id}", headers=auth_headers)
    assert removed.status_code == 204, removed.text

    # The suite hands the app its own session, with `expire_on_commit=False`,
    # so the `User` it already loaded keeps the membership collection it was
    # loaded with. A real request opens a fresh session and sees the delete;
    # this is how the test gets the same view.
    db_session.expire_all()

    assert (await _login(client, email)).status_code == 403


@pytest.mark.asyncio
async def test_a_membership_in_another_clinic_still_signs_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The rule is "no clinic at all", not "not my clinic"."""
    other = await _other_clinic(db_session)
    stranded = await _user(db_session, f"stranded-{uuid4().hex[:8]}@example.com")
    db_session.add(ClinicMembership(user_id=stranded.id, clinic_id=other.id, role="admin"))
    await db_session.commit()

    assert (await _login(client, stranded.email)).status_code == 200


# --- the operator switch is gone --------------------------------------


@pytest.mark.asyncio
async def test_no_endpoint_lets_a_clinic_touch_an_outside_account(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    db_session: AsyncSession,
) -> None:
    """`PATCH /auth/users/{id}/active` was a cross-tenant kill switch.

    It refused to act on this clinic's own staff (409) and existed only
    for everybody else's, which made it a way for one tenant to stop
    another tenant's people signing in. Removed rather than narrowed:
    there is no version of "disable somebody else's staff" that belongs
    to a clinic admin.
    """
    outsider = await _user(db_session, f"outsider-{uuid4().hex[:8]}@example.com")
    other = await _other_clinic(db_session)
    db_session.add(ClinicMembership(user_id=outsider.id, clinic_id=other.id, role="dentist"))
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/auth/users/{outsider.id}/active",
        json={"is_active": False},
        headers=auth_headers,
    )

    assert response.status_code in (404, 405), response.text

    # And the account is untouched, which is the thing that matters.
    await db_session.refresh(outsider)
    assert outsider.is_active is True


# --- one account, two clinics -----------------------------------------


@pytest.mark.asyncio
async def test_disabling_a_two_clinic_account_is_refused(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    db_session: AsyncSession,
) -> None:
    """`is_active` belongs to the account, and an account is global.

    So switching it off for somebody who is also staff somewhere else
    would end their sign-in there too — this clinic reaching into
    another's. Refused, with the per-clinic action named: removing them
    from this clinic, which login already honours.
    """
    shared = await _user(db_session, f"shared-{uuid4().hex[:8]}@example.com")
    other = await _other_clinic(db_session)
    db_session.add_all(
        [
            ClinicMembership(user_id=shared.id, clinic_id=test_clinic.id, role="assistant"),
            ClinicMembership(user_id=shared.id, clinic_id=other.id, role="dentist"),
        ]
    )
    await db_session.commit()

    response = await client.put(
        f"/api/v1/auth/users/{shared.id}",
        json={"is_active": False},
        headers=auth_headers,
    )

    assert response.status_code == 409, response.text
    await db_session.refresh(shared)
    assert shared.is_active is True, "the other clinic's sign-in was ended anyway"


@pytest.mark.asyncio
async def test_disabling_an_account_of_this_clinic_only_still_works(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    db_session: AsyncSession,
) -> None:
    """The positive control: the guard must not block ordinary staff."""
    ours = await _user(db_session, f"ours-{uuid4().hex[:8]}@example.com")
    db_session.add(ClinicMembership(user_id=ours.id, clinic_id=test_clinic.id, role="assistant"))
    await db_session.commit()

    response = await client.put(
        f"/api/v1/auth/users/{ours.id}",
        json={"is_active": False},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    await db_session.refresh(ours)
    assert ours.is_active is False
