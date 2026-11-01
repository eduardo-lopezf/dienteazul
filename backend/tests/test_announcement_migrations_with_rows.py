"""Migration `0028`, run against a database that already has notices in it.

The empty-database round-trip cannot see this one. `0028` adds
`announcements.options` and, with it, a check that ties it to the kind:
``(kind = 'survey') = (options IS NOT NULL)``. Every row that exists when
the migration runs is a `maintenance` or a `feature` with no options, so
either the check holds for all of them or it holds for none — and the
difference only shows on a table that is not empty.

It nearly held for none. A JSONB column writes Python ``None`` as the
JSON value ``null``, which **is not** SQL NULL: ``options IS NOT NULL``
was true for every notice, the check read each one as a survey offering
nothing, and the clinic's own banner stopped being publishable. The
column carries ``none_as_null=True`` for that reason, and this is the
test that fails if it is ever taken off.

Marked `alembic_roundtrip` like its neighbours: it rebuilds the schema of
the database it is pointed at, so it must not run inside the ordinary
suite.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import asyncpg
import pytest

from .test_clinical_record_migrations_with_rows import (
    CLINIC_ID,
    _alembic,
    _drop_everything,
    _dsn,
    _insert,
    _run,
)

pytestmark = pytest.mark.alembic_roundtrip

BEFORE = "0027"
AFTER = "0028"
QUESTIONNAIRE = "0029"

OTHER_CLINIC = "99999999-9999-9999-9999-999999999999"


async def _seed_notices() -> None:
    """What a running installation had before surveys existed: a notice to
    everyone, and one aimed at a single inquilino."""
    conn = await asyncpg.connect(_dsn())
    try:
        await _insert(
            conn,
            # `account_tier` is constrained by a CHECK the generic filler
            # cannot guess, so it is named.
            "clinics",
            {"id": CLINIC_ID, "name": "Scratch", "tax_id": "B1", "account_tier": "clinic"},
        )
        await _insert(
            conn,
            "announcements",
            {
                "id": "aaaaaaaa-0000-0000-0000-000000000001",
                "kind": "maintenance",
                "message": "El domingo hay mantenimiento",
                # NOT NULL with no default, and the generic filler leaves
                # timestamps alone.
                "starts_at": datetime.now(UTC),
            },
        )
        await _insert(
            conn,
            "announcements",
            {
                "id": "aaaaaaaa-0000-0000-0000-000000000002",
                "kind": "feature",
                "message": "Ahora hay recordatorios",
                "clinic_ids": json.dumps([CLINIC_ID]),
                "starts_at": datetime.now(UTC),
            },
        )
    finally:
        await conn.close()


def test_existing_notices_survive_the_survey_migration() -> None:
    asyncio.run(_drop_everything())
    _alembic("stamp", "base")
    _alembic("upgrade", BEFORE)
    asyncio.run(_seed_notices())

    before = asyncio.run(_run("SELECT id, kind, message FROM announcements ORDER BY message"))
    assert [row["kind"] for row in before] == ["feature", "maintenance"]

    _alembic("upgrade", AFTER)

    after = asyncio.run(
        _run("SELECT id, kind, message, options FROM announcements ORDER BY message")
    )
    # The rows are the same rows, and none of them became a survey.
    assert [(row["id"], row["kind"], row["message"]) for row in after] == [
        (row["id"], row["kind"], row["message"]) for row in before
    ]
    assert [row["options"] for row in after] == [None, None]


def test_after_the_migration_the_kind_and_the_options_agree() -> None:
    asyncio.run(_drop_everything())
    _alembic("stamp", "base")
    _alembic("upgrade", BEFORE)
    asyncio.run(_seed_notices())
    _alembic("upgrade", AFTER)

    async def _write(kind: str, options: str | None) -> str | None:
        """What the database says to a notice of this shape."""
        conn = await asyncpg.connect(_dsn())
        try:
            await conn.execute(
                "INSERT INTO announcements (id, kind, message, options, starts_at, "
                "created_at, updated_at) VALUES (gen_random_uuid(), $1, 'x', $2::jsonb, "
                "now(), now(), now())",
                kind,
                options,
            )
        except asyncpg.exceptions.CheckViolationError as refused:
            return refused.constraint_name
        finally:
            await conn.close()
        return None

    # A survey with choices, and a notice without them: both fine.
    assert asyncio.run(_write("survey", json.dumps(["Sí", "No"]))) is None
    assert asyncio.run(_write("maintenance", None)) is None

    # The two halves of the check, each refused.
    assert asyncio.run(_write("survey", None)) == "ck_announcements_survey_options"
    assert (
        asyncio.run(_write("feature", json.dumps(["Sí", "No"])))
        == "ck_announcements_survey_options"
    )
    # And a kind that does not exist is still a kind that does not exist.
    assert asyncio.run(_write("outage", None)) == "ck_announcements_kind"


# --- 0029: the survey becomes a questionnaire ------------------------------


def test_the_questionnaire_migration_keeps_the_ordinary_notices() -> None:
    """``0029`` replaces a format, on a table that is mostly not it.

    It drops ``options`` and the old answers and deletes the surveys
    written under ``0028`` — the two shapes do not map onto each other.
    What it must not touch is everything else: the maintenance windows
    and the novelties, which are the rows a running installation actually
    has.
    """
    asyncio.run(_drop_everything())
    _alembic("stamp", "base")
    _alembic("upgrade", AFTER)
    asyncio.run(_seed_notices())

    async def _a_survey_with_an_answer() -> None:
        conn = await asyncpg.connect(_dsn())
        try:
            survey = "aaaaaaaa-0000-0000-0000-00000000000f"
            await conn.execute(
                "INSERT INTO announcements (id, kind, message, options, starts_at, "
                "created_at, updated_at) VALUES ($1, 'survey', '¿Sí o no?', $2::jsonb, "
                "now(), now(), now())",
                survey,
                json.dumps(["Sí", "No"]),
            )
            await _insert(
                conn,
                "users",
                {"id": "bbbbbbbb-0000-0000-0000-000000000001", "email": "a@b.c"},
            )
            await conn.execute(
                "INSERT INTO announcement_responses (id, announcement_id, clinic_id, "
                "user_id, option_index, created_at, updated_at) VALUES "
                "(gen_random_uuid(), $1, $2, $3, 0, now(), now())",
                survey,
                CLINIC_ID,
                "bbbbbbbb-0000-0000-0000-000000000001",
            )
        finally:
            await conn.close()

    asyncio.run(_a_survey_with_an_answer())
    before = asyncio.run(_run("SELECT id, kind, message FROM announcements ORDER BY message"))
    assert len(before) == 3

    _alembic("upgrade", QUESTIONNAIRE)

    after = asyncio.run(
        _run("SELECT id, kind, message, title, questions FROM announcements ORDER BY message")
    )
    # The survey and its answers are gone; the other two are untouched.
    assert [row["kind"] for row in after] == ["feature", "maintenance"]
    assert [row["message"] for row in after] == [
        row["message"] for row in before if row["kind"] != "survey"
    ]
    assert [row["questions"] for row in after] == [None, None]
    assert [row["title"] for row in after] == [None, None]

    tables = asyncio.run(
        _run(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN ('announcement_answers', 'announcement_responses')"
        )
    )
    assert [row["table_name"] for row in tables] == ["announcement_answers"]


def test_after_0029_a_survey_needs_questions_and_a_notice_needs_none() -> None:
    """The check follows the column it was rewritten for."""
    asyncio.run(_drop_everything())
    _alembic("stamp", "base")
    _alembic("upgrade", QUESTIONNAIRE)

    async def _write(kind: str, questions: str | None) -> str | None:
        conn = await asyncpg.connect(_dsn())
        try:
            await conn.execute(
                "INSERT INTO announcements (id, kind, message, questions, starts_at, "
                "created_at, updated_at) VALUES (gen_random_uuid(), $1, 'x', $2::jsonb, "
                "now(), now(), now())",
                kind,
                questions,
            )
        except asyncpg.exceptions.CheckViolationError as refused:
            return refused.constraint_name
        finally:
            await conn.close()
        return None

    asked = json.dumps([{"id": "q1", "kind": "yes_no", "text": "¿Sí?"}])
    assert asyncio.run(_write("survey", asked)) is None
    assert asyncio.run(_write("maintenance", None)) is None
    assert asyncio.run(_write("survey", None)) == "ck_announcements_survey_questions"
    assert asyncio.run(_write("feature", asked)) == "ck_announcements_survey_questions"
