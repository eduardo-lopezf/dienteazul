"""New rows get UUID version 7 keys (``app.core.ids``); a token that must be
unguessable stays version 4."""

from __future__ import annotations

import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.ids import uuid7
from app.database import Base


def test_a_key_is_a_version_7_uuid() -> None:
    key = uuid7()
    assert (key.version, key.variant) == (7, uuid.RFC_4122)


def test_a_key_made_later_sorts_later() -> None:
    earlier = uuid7()
    time.sleep(0.002)
    assert uuid7() > earlier


def test_keys_are_unique() -> None:
    assert len({uuid7() for _ in range(10_000)}) == 10_000


def test_a_key_carries_when_it_was_made() -> None:
    before = time.time_ns() // 1_000_000
    key = uuid7()
    assert before <= key.int >> 80 <= time.time_ns() // 1_000_000


async def test_a_new_row_gets_a_version_7_key(db_session: AsyncSession) -> None:
    clinic = Clinic(name="Clínica", tax_id="XAXX010101000", account_tier="clinic", timezone="UTC")
    db_session.add(clinic)
    await db_session.flush()
    assert clinic.id.version == 7


def test_every_uuid_primary_key_defaults_to_version_7() -> None:
    """A model added later with ``default=uuid4`` would make random keys
    again; this lists any that does."""
    random_keys = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.primary_key.columns
        if column.default is not None
        and getattr(column.default, "arg", None) is not None
        and getattr(column.default.arg, "__name__", "") == "uuid4"
    ]
    assert random_keys == []


def test_the_public_budget_token_stays_random() -> None:
    # It is the secret in the patient's link: a v7 one would tell when it
    # was made and carry fewer random bits.
    column = Base.metadata.tables["budgets"].columns["public_token"]
    assert column.default.arg.__name__ == "uuid4"
