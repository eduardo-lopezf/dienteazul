"""The demo shelf obeys the same rule as the application.

A seeded snapshot that disagreed with its ledger would make the stock
screen lie on the very first look, and the reconciliation endpoint would
report drift on a database nobody had touched. So the seed posts
movements like everything else (ADR 0065), and this says so.

It also pins the figures the e2e test reads: a seed changed without its
tests is three CI failures later.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, User
from app.modules.inventory.models import InventoryItem, InventoryMovement, InventoryStockLevel
from app.modules.inventory.seed import seed_inventory_demo
from app.modules.inventory.service import StockService


@pytest.fixture
async def staff_id(db_session: AsyncSession, test_clinic: Clinic):
    """Whoever put the delivery away. A real user: the movement's
    ``performed_by`` is a foreign key into ``users``."""
    return await db_session.scalar(select(User.id).limit(1))


async def test_the_demo_shelf_agrees_with_its_ledger(
    db_session: AsyncSession, test_clinic: Clinic, staff_id
) -> None:
    stats = await seed_inventory_demo(db_session, clinic_id=test_clinic.id, user_id=staff_id)
    await db_session.commit()

    assert stats["skipped"] is False
    assert stats["items"] == 7
    assert stats["lots"] == 6

    ledger = await db_session.scalar(
        select(func.coalesce(func.sum(InventoryMovement.quantity_base), 0)).where(
            InventoryMovement.clinic_id == test_clinic.id
        )
    )
    levels = await db_session.scalar(
        select(func.coalesce(func.sum(InventoryStockLevel.quantity), 0)).where(
            InventoryStockLevel.clinic_id == test_clinic.id
        )
    )
    assert Decimal(ledger) == Decimal(levels)

    result = await StockService.reconcile(db_session, test_clinic.id)
    assert result["corrected"] == 0


async def test_seeding_twice_changes_nothing(
    db_session: AsyncSession, test_clinic: Clinic, staff_id
) -> None:
    await seed_inventory_demo(db_session, clinic_id=test_clinic.id, user_id=staff_id)
    await db_session.commit()
    before = await db_session.scalar(
        select(func.count())
        .select_from(InventoryItem)
        .where(InventoryItem.clinic_id == test_clinic.id)
    )

    again = await seed_inventory_demo(db_session, clinic_id=test_clinic.id, user_id=staff_id)
    await db_session.commit()

    assert again["skipped"] is True
    after = await db_session.scalar(
        select(func.count())
        .select_from(InventoryItem)
        .where(InventoryItem.clinic_id == test_clinic.id)
    )
    assert after == before


async def test_the_seed_shows_every_state_the_screen_can_be_in(
    db_session: AsyncSession, test_clinic: Clinic, staff_id
) -> None:
    """What the e2e test and the manual's screenshots depend on."""
    await seed_inventory_demo(db_session, clinic_id=test_clinic.id, user_id=staff_id)
    await db_session.commit()

    alerts = await StockService.alerts(db_session, test_clinic.id)
    assert [line["item_code"] for line in alerts["low_stock"]] == ["EYE-DES"]
    assert [line["lot_code"] for line in alerts["expired"]] == ["ADH-2510"]
    assert {line["lot_code"] for line in alerts["expiring"]} == {"ART-2611", "C-A2-2612"}

    lines = await StockService.levels(db_session, test_clinic.id)
    gloves = [line for line in lines if line["item_code"] == "GUA-NIT-M"]
    # Split between two locations, and the total is what the badge reads.
    assert {line["location_name"] for line in gloves} == {"Almacén", "Gabinete 1"}
    assert gloves[0]["item_total"] == Decimal("332.000")
    assert gloves[0]["is_low"] is False
