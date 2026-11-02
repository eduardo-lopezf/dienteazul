"""Inventory background tasks (APScheduler entry points).

One job, run once a day: say what is running out and what is about to
expire. The signals are *derived* — nothing stores "this article is low",
because the ledger already knows — and the only state kept is when each
article and lot was last announced, so the clinic is not told the same
thing every morning until somebody buys something.

That mark lives in the database (``low_stock_notified_at``,
``expiry_notified_at``) rather than in a module-level variable, because
this runs in one of several processes (ADR 0051).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text

from app.core.events import EventType, event_bus
from app.database import async_session_maker

from .models import InventoryItem, InventoryLot
from .service import EXPIRY_WINDOW_DAYS, StockService

logger = logging.getLogger(__name__)

_CLINIC_CONCURRENCY = 5

#: How long an announcement stands before the same article or lot is
#: announced again. A week: long enough not to nag, short enough that
#: something ignored in a busy fortnight comes back.
QUIET_DAYS = 7


async def _list_clinics() -> list[UUID]:
    async with async_session_maker() as db:
        rows = (await db.execute(text("SELECT id FROM clinics WHERE deactivated_at IS NULL"))).all()
    return [row.id for row in rows]


def _is_quiet(last: datetime | None, now: datetime) -> bool:
    """Whether this one has been announced recently enough to skip."""
    return last is not None and (now - last) < timedelta(days=QUIET_DAYS)


async def _announce_for_clinic(clinic_id: UUID, sem: asyncio.Semaphore) -> None:
    async with sem, async_session_maker() as db:
        try:
            now = datetime.now(UTC)
            alerts = await StockService.alerts(db, clinic_id)

            for line in alerts["low_stock"]:
                item = await db.scalar(
                    select(InventoryItem).where(InventoryItem.id == line["item_id"])
                )
                if item is None or _is_quiet(item.low_stock_notified_at, now):
                    continue
                event_bus.publish_after_commit(
                    db,
                    EventType.INVENTORY_STOCK_LOW,
                    {
                        "clinic_id": str(clinic_id),
                        "item_id": str(item.id),
                        "item_name": item.name,
                        "on_hand": str(line["item_total"]),
                        "reorder_point": str(item.reorder_point),
                        "reorder_quantity": (
                            str(item.reorder_quantity) if item.reorder_quantity else None
                        ),
                    },
                )
                item.low_stock_notified_at = now

            for line in alerts["expiring"] + alerts["expired"]:
                if line["lot_id"] is None:
                    continue
                lot = await db.scalar(select(InventoryLot).where(InventoryLot.id == line["lot_id"]))
                if lot is None or _is_quiet(lot.expiry_notified_at, now):
                    continue
                event_bus.publish_after_commit(
                    db,
                    EventType.INVENTORY_ITEM_EXPIRING,
                    {
                        "clinic_id": str(clinic_id),
                        "item_id": str(line["item_id"]),
                        "item_name": line["item_name"],
                        "lot_id": str(lot.id),
                        "lot_code": lot.lot_code,
                        "expires_on": lot.expires_on.isoformat() if lot.expires_on else None,
                        "days_to_expiry": line["days_to_expiry"],
                        "quantity": str(line["quantity"]),
                    },
                )
                lot.expiry_notified_at = now

            await db.commit()
        except Exception as exc:
            logger.error("inventory alerts failed for clinic %s: %s", clinic_id, exc, exc_info=True)
            await db.rollback()


async def announce_stock_alerts() -> None:
    """Publish the low-stock and expiry signals of every active clinic.

    Idempotent within ``QUIET_DAYS``: re-running announces nothing new.
    The inventory itself notifies nobody — ``notifications`` decides what
    to do with these events.
    """
    sem = asyncio.Semaphore(_CLINIC_CONCURRENCY)
    clinics = await _list_clinics()
    await asyncio.gather(*(_announce_for_clinic(clinic_id, sem) for clinic_id in clinics))
    logger.info(
        "inventory alerts swept %d clinics (expiry window %d days)",
        len(clinics),
        EXPIRY_WINDOW_DAYS,
    )
