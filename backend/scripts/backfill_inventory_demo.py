#!/usr/bin/env python3
"""Put the inventory demo shelf into a clinic that already exists.

``seed_demo.py`` refuses to run against a database that already holds
data, so a clinic seeded before the inventory existed would never get
its articles — it would open Existencias and find it empty with nothing
to try. This is the backfill for that case.

Idempotent in both directions: it does nothing when the module is not
installed, and nothing when the clinic already has articles.

Usage::

    docker compose exec -T backend bash -c \\
        "PYTHONPATH=/app python /app/scripts/backfill_inventory_demo.py"
    # ...or one clinic only:
    ... backfill_inventory_demo.py --clinic <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text  # noqa: E402

from app.core.plugins.db_models import ModuleRecord  # noqa: E402
from app.database import async_session_maker  # noqa: E402


async def _installed(db) -> bool:
    state = await db.scalar(select(ModuleRecord.state).where(ModuleRecord.name == "inventory"))
    return state == "installed"


async def _clinics(db, only: UUID | None) -> list[UUID]:
    if only is not None:
        return [only]
    rows = (await db.execute(text("SELECT id FROM clinics WHERE deactivated_at IS NULL"))).all()
    return [row.id for row in rows]


async def _staff_id(db, clinic_id: UUID) -> UUID | None:
    """Somebody of this clinic to attribute the movements to."""
    return await db.scalar(
        text(
            "SELECT user_id FROM clinic_memberships "
            "WHERE clinic_id = :clinic_id ORDER BY created_at LIMIT 1"
        ).bindparams(clinic_id=clinic_id)
    )


async def main(only: UUID | None) -> int:
    # Import every module's models before the first query. The ORM
    # resolves `Clinic`'s relationships by name at mapper configuration
    # time, and in a script where only this module has been imported
    # those names do not exist yet ("failed to locate a name 'Patient'").
    from app.core.plugins.loader import discover_modules
    from app.modules.inventory.seed import seed_inventory_demo

    discover_modules()

    async with async_session_maker() as db:
        if not await _installed(db):
            print("inventory is not installed in this deployment — nothing to do")
            return 0

        for clinic_id in await _clinics(db, only):
            user_id = await _staff_id(db, clinic_id)
            if user_id is None:
                print(f"{clinic_id}: no members, skipped")
                continue
            stats = await seed_inventory_demo(db, clinic_id=clinic_id, user_id=user_id)
            if stats["skipped"]:
                print(f"{clinic_id}: already has articles, left untouched")
                continue
            print(
                f"{clinic_id}: {stats['items']} articles, "
                f"{stats['lots']} lots, {stats['movements']} movements"
            )
        await db.commit()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clinic", type=UUID, default=None, help="only this clinic")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.clinic)))
