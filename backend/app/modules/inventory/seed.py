"""Demo stock for the inventory module.

Every figure here is produced by posting movements through
``StockService``, never by writing ``inv_stock_levels`` — the demo has to
obey the same rule as the application (ADR 0065), and a seeded snapshot
that disagreed with its ledger would make the reconciliation screen lie
on the very first look.

The dataset is chosen to show each state the screen can be in: an
article below its reorder point, a lot that expires inside the warning
window, a lot that has already expired and is still counted, stock split
between the storeroom and a cabinet, and one article that tracks no lots
at all. The e2e tests read these, so changing the numbers means changing
them too.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import InventoryItem
from .service import ItemService, LocationService, LotService, StockService

LOCATIONS = [
    {"name": "Almacén", "kind": "warehouse", "is_default": True},
    {"name": "Gabinete 1", "kind": "cabinet", "is_default": False},
    {"name": "Nevera", "kind": "fridge", "is_default": False},
]

#: ``lots`` entries are ``(code, days_until_expiry | None, quantity)``;
#: ``receipts`` are ``(location, quantity)`` for articles without lots.
ITEMS = [
    {
        "code": "GUA-NIT-M",
        "name": "Guantes de nitrilo talla M",
        "category": "consumable",
        "base_unit": "par",
        "reorder_point": "40",
        "reorder_quantity": "400",
        "cost_per_base_unit": "0.12",
        "receipts": [("Almacén", "300"), ("Gabinete 1", "50")],
    },
    {
        # Below its reorder point on purpose: the screen needs a row that
        # is actually low, or the badge is never seen.
        "code": "EYE-DES",
        "name": "Eyectores desechables",
        "category": "consumable",
        "base_unit": "unidad",
        "reorder_point": "200",
        "reorder_quantity": "1000",
        "cost_per_base_unit": "0.03",
        "receipts": [("Almacén", "120")],
    },
    {
        "code": "COM-A2",
        "name": "Composite A2 (jeringa 4 g)",
        "category": "restorative",
        "base_unit": "jeringa",
        "reorder_point": "6",
        "reorder_quantity": "20",
        "cost_per_base_unit": "18.50",
        "lots": [("C-A2-2708", 420, "12"), ("C-A2-2612", 45, "3")],
        "location": "Gabinete 1",
    },
    {
        "code": "ANE-ART-4",
        "name": "Articaína 4% con epinefrina",
        "category": "anaesthetic",
        "base_unit": "carpule",
        "reorder_point": "50",
        "reorder_quantity": "200",
        "cost_per_base_unit": "0.65",
        "lots": [("ART-2801", 480, "150"), ("ART-2611", 30, "40")],
        "location": "Nevera",
    },
    {
        # Already past its date and still on the shelf: the case the
        # expiry column exists for.
        "code": "ADH-UNI",
        "name": "Adhesivo universal (5 ml)",
        "category": "restorative",
        "base_unit": "ml",
        "reorder_point": "10",
        "reorder_quantity": "30",
        "cost_per_base_unit": "7.90",
        "lots": [("ADH-2510", -12, "5"), ("ADH-2806", 300, "20")],
        "location": "Gabinete 1",
    },
    {
        "code": "FRE-DIA",
        "name": "Fresas de diamante troncocónicas",
        "category": "instrument",
        "base_unit": "unidad",
        "reorder_point": "15",
        "reorder_quantity": "50",
        "cost_per_base_unit": "2.40",
        "receipts": [("Almacén", "60")],
    },
    {
        "code": "BOL-EST",
        "name": "Bolsas de esterilización 90x230",
        "category": "hygiene",
        "base_unit": "unidad",
        "reorder_point": "150",
        "reorder_quantity": "500",
        "cost_per_base_unit": "0.05",
        "receipts": [("Almacén", "400")],
    },
]

#: What the clinic has used since the delivery, so the ledger has
#: something to explain: ``(code, location, quantity, note)``.
CONSUMPTIONS = [
    ("GUA-NIT-M", "Gabinete 1", "18", "Jornada del lunes"),
    ("EYE-DES", "Almacén", "30", "Reposición de gabinetes"),
    ("FRE-DIA", "Almacén", "4", "Endodoncia de la tarde"),
]


async def seed_inventory_demo(db: AsyncSession, *, clinic_id: UUID, user_id: UUID) -> dict:
    """Create the demo shelf. Idempotent: a clinic that already has
    articles is left exactly as it is."""
    existing = await db.scalar(
        select(func.count()).select_from(InventoryItem).where(InventoryItem.clinic_id == clinic_id)
    )
    if existing:
        return {"items": 0, "movements": 0, "lots": 0, "skipped": True}

    locations: dict[str, UUID] = {}
    for spec in LOCATIONS:
        location = await LocationService.create(db, clinic_id, dict(spec))
        locations[str(spec["name"])] = location.id

    today = datetime.now(UTC).date()
    items: dict[str, UUID] = {}
    movements = lots = 0

    for spec in ITEMS:
        item = await ItemService.create(
            db,
            clinic_id,
            {
                "code": spec["code"],
                "name": spec["name"],
                "category": spec["category"],
                "base_unit": spec["base_unit"],
                "reorder_point": Decimal(str(spec["reorder_point"])),
                "reorder_quantity": Decimal(str(spec["reorder_quantity"])),
                "cost_per_base_unit": Decimal(str(spec["cost_per_base_unit"])),
                "tracks_lots": "lots" in spec,
            },
        )
        items[str(spec["code"])] = item.id

        for code, offset_days, amount in spec.get("lots", []):
            lot = await LotService.create(
                db,
                clinic_id,
                item.id,
                {"lot_code": code, "expires_on": today + timedelta(days=offset_days)},
            )
            lots += 1
            await StockService.post(
                db,
                clinic_id,
                user_id,
                item_id=item.id,
                location_id=locations[str(spec["location"])],
                lot_id=lot.id,
                quantity_base=Decimal(amount),
                reason="purchase_receipt",
                cost_per_base_unit=Decimal(str(spec["cost_per_base_unit"])),
            )
            movements += 1

        for location_name, amount in spec.get("receipts", []):
            await StockService.post(
                db,
                clinic_id,
                user_id,
                item_id=item.id,
                location_id=locations[location_name],
                lot_id=None,
                quantity_base=Decimal(amount),
                reason="purchase_receipt",
                cost_per_base_unit=Decimal(str(spec["cost_per_base_unit"])),
            )
            movements += 1

    for code, location_name, amount, note in CONSUMPTIONS:
        await StockService.post(
            db,
            clinic_id,
            user_id,
            item_id=items[code],
            location_id=locations[location_name],
            lot_id=None,
            quantity_base=Decimal(amount),
            reason="consumption",
            note=note,
        )
        movements += 1

    await db.flush()
    return {"items": len(items), "movements": movements, "lots": lots, "skipped": False}
