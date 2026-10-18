"""``pro_0004`` run against a database that has practices in it.

The revision gives the holder of every existing individual practice their
professional profile. It is a data migration over populated tables — the
class of change that has broken a deploy here — so it is tested with rows:

- a basic practice whose holder has no profile gets one, linked to them;
- a practice whose holder already has a linked profile gets no second one;
- a clinic tier gets nothing — it builds its directory;
- running it twice changes nothing.

Marked ``alembic_roundtrip``: it rebuilds the schema of the database it is
pointed at, so it must not run inside the ordinary suite.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.test_clinical_record_migrations_with_rows import (
    _alembic,
    _drop_everything,
    _insert,
    _run,
)

pytestmark = pytest.mark.alembic_roundtrip

BEFORE = "pro_0003"
AFTER = "pro_0004"

BASIC = "a1111111-1111-1111-1111-111111111111"
LINKED = "a2222222-2222-2222-2222-222222222222"
CLINIC = "a3333333-3333-3333-3333-333333333333"
HOLDER = "b1111111-1111-1111-1111-111111111111"
LINKED_HOLDER = "b2222222-2222-2222-2222-222222222222"
CLINIC_ADMIN = "b3333333-3333-3333-3333-333333333333"
EXISTING_PROFILE = "c2222222-2222-2222-2222-222222222222"


async def _seed() -> None:
    import asyncpg

    from tests.test_clinical_record_migrations_with_rows import _dsn

    conn = await asyncpg.connect(_dsn())
    try:
        for clinic_id, tier in ((BASIC, "basic"), (LINKED, "medium"), (CLINIC, "clinic")):
            await _insert(
                conn,
                "clinics",
                {"id": clinic_id, "name": tier, "tax_id": tier, "account_tier": tier},
            )
        for user_id, email, licence in (
            (HOLDER, "holder@example.com", "1234567"),
            (LINKED_HOLDER, "linked@example.com", None),
            (CLINIC_ADMIN, "admin@example.com", None),
        ):
            await _insert(
                conn,
                "users",
                {
                    "id": user_id,
                    "email": email,
                    "first_name": "Aurelia",
                    "last_name": "Zamarripa",
                    "professional_id": licence,
                    "password_hash": "x",
                    "is_active": True,
                },
            )
        for n, (clinic_id, user_id) in enumerate(
            ((BASIC, HOLDER), (LINKED, LINKED_HOLDER), (CLINIC, CLINIC_ADMIN))
        ):
            await _insert(
                conn,
                "clinic_memberships",
                {
                    "id": f"d{n}111111-1111-1111-1111-111111111111",
                    "clinic_id": clinic_id,
                    "user_id": user_id,
                    "role": "admin",
                },
            )
        await _insert(
            conn,
            "professionals",
            {
                "id": EXISTING_PROFILE,
                "clinic_id": LINKED,
                "user_id": LINKED_HOLDER,
                "first_name": "Ya",
                "last_name": "Ligado",
                "professional_type": "dentist",
                "is_active": True,
            },
        )
    finally:
        await conn.close()


async def _profiles() -> list:
    return await _run(
        "SELECT clinic_id::text, user_id::text, first_name, license_number, professional_type "
        "FROM professionals ORDER BY clinic_id"
    )


def test_existing_individual_practices_get_their_holders_profile() -> None:
    asyncio.run(_drop_everything())
    _alembic("stamp", "base")
    _alembic("upgrade", "heads")
    _alembic("downgrade", BEFORE)
    asyncio.run(_seed())

    _alembic("upgrade", AFTER)
    rows = asyncio.run(_profiles())

    by_clinic = {}
    for row in rows:
        by_clinic.setdefault(row["clinic_id"], []).append(row)
    [made] = by_clinic[BASIC]
    assert made["user_id"] == HOLDER
    assert (made["first_name"], made["license_number"], made["professional_type"]) == (
        "Aurelia",
        "1234567",
        "dentist",
    )
    [kept] = by_clinic[LINKED]
    assert kept["first_name"] == "Ya", "a holder already linked gets no second profile"
    assert CLINIC not in by_clinic, "a clinic tier builds its own directory"

    # Down and up again: nothing is taken away, nothing is made twice.
    _alembic("downgrade", BEFORE)
    _alembic("upgrade", AFTER)
    assert len(asyncio.run(_profiles())) == len(rows)

    _alembic("upgrade", "heads")
