"""The ledger is the truth and the snapshot is derived from it (ADR 0065).

Everything here defends that one sentence. The reconciliation test is the
criterion the feature brief sets for layer 0: after an arbitrary sequence
of movements, the sum of ``inv_movements`` equals ``inv_stock_levels`` for
every article/location/lot, and recomputing corrects nothing.

The rest pin the rules the arithmetic depends on: a lot-tracked article
never moves without its lot, stock only goes negative through an
adjustment, a transfer is two lines that leave the total alone, and a
physical count posts the difference rather than overwriting the number.
"""

from __future__ import annotations

import random
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.events import EventType, event_bus
from app.modules.inventory.models import (
    InventoryItem,
    InventoryMovement,
    InventoryStockLevel,
)
from app.modules.inventory.service import (
    InventoryError,
    ItemService,
    LocationService,
    LotService,
    StockService,
)

MODULE_ROOT = Path(__file__).resolve().parents[3] / "app" / "modules" / "inventory"


@pytest.fixture
async def shelf(db_session: AsyncSession, test_clinic: Clinic) -> dict:
    """One plain article, one lot-tracked article, two locations."""
    gloves = await ItemService.create(
        db_session,
        test_clinic.id,
        {
            "code": "GUA-100",
            "name": "Guantes nitrilo M",
            "base_unit": "par",
            "category": "consumable",
            "purchase_presentations": [{"label": "caja de 100", "factor": Decimal("100")}],
            "tracks_lots": False,
            "reorder_point": Decimal("20"),
            "reorder_quantity": Decimal("200"),
        },
    )
    articaine = await ItemService.create(
        db_session,
        test_clinic.id,
        {
            "code": "ANE-ART",
            "name": "Articaína 4% con epinefrina",
            "base_unit": "carpule",
            "category": "anaesthetic",
            "tracks_lots": True,
            "reorder_point": Decimal("10"),
        },
    )
    store = await LocationService.create(
        db_session, test_clinic.id, {"name": "Almacén", "kind": "warehouse", "is_default": True}
    )
    cabinet = await LocationService.create(
        db_session, test_clinic.id, {"name": "Gabinete 1", "kind": "cabinet"}
    )
    lot = await LotService.create(
        db_session,
        test_clinic.id,
        articaine.id,
        {"lot_code": "L-2027-03", "expires_on": None},
    )
    await db_session.commit()
    return {
        "clinic_id": test_clinic.id,
        "gloves": gloves,
        "articaine": articaine,
        "store": store,
        "cabinet": cabinet,
        "lot": lot,
    }


async def _ledger_by_triple(db: AsyncSession, clinic_id: UUID) -> dict[tuple, Decimal]:
    rows = await db.execute(
        select(
            InventoryMovement.item_id,
            InventoryMovement.location_id,
            InventoryMovement.lot_id,
            func.sum(InventoryMovement.quantity_base),
        )
        .where(InventoryMovement.clinic_id == clinic_id)
        .group_by(
            InventoryMovement.item_id,
            InventoryMovement.location_id,
            InventoryMovement.lot_id,
        )
    )
    return {(i, loc, lot): Decimal(total) for i, loc, lot, total in rows.all()}


async def _levels_by_triple(db: AsyncSession, clinic_id: UUID) -> dict[tuple, Decimal]:
    rows = await db.execute(
        select(InventoryStockLevel).where(InventoryStockLevel.clinic_id == clinic_id)
    )
    return {
        (level.item_id, level.location_id, level.lot_id): Decimal(level.quantity)
        for level in rows.scalars().all()
    }


# --- The invariant --------------------------------------------------------


async def test_the_snapshot_always_equals_the_ledger(db_session: AsyncSession, shelf: dict) -> None:
    """Layer 0's success criterion, over a randomised sequence.

    Seeded so a failure is reproducible: an inventory bug that only shows
    up on a Tuesday is worse than no test.
    """
    rng = random.Random(20261101)
    clinic_id = shelf["clinic_id"]
    locations = [shelf["store"].id, shelf["cabinet"].id]

    # Stock has to arrive before it can be used, so the sequence opens
    # with a receipt in each location and then moves at random.
    for location_id in locations:
        await StockService.post(
            db_session,
            clinic_id,
            None,
            item_id=shelf["gloves"].id,
            location_id=location_id,
            lot_id=None,
            quantity_base=Decimal("500"),
            reason="purchase_receipt",
        )
        await StockService.post(
            db_session,
            clinic_id,
            None,
            item_id=shelf["articaine"].id,
            location_id=location_id,
            lot_id=shelf["lot"].id,
            quantity_base=Decimal("200"),
            reason="purchase_receipt",
        )

    for _ in range(60):
        lot_tracked = rng.choice([True, False])
        item_id = shelf["articaine"].id if lot_tracked else shelf["gloves"].id
        lot_id = shelf["lot"].id if lot_tracked else None
        reason = rng.choice(
            ["purchase_receipt", "consumption", "expiry_write_off", "return", "adjustment"]
        )
        quantity = Decimal(rng.randint(1, 9))
        if reason == "adjustment" and rng.choice([True, False]):
            quantity = -quantity
        try:
            await StockService.post(
                db_session,
                clinic_id,
                None,
                item_id=item_id,
                location_id=rng.choice(locations),
                lot_id=lot_id,
                quantity_base=quantity,
                reason=reason,
                note="randomised" if reason == "adjustment" else None,
            )
        except InventoryError:
            # A refusal is a legitimate outcome (not enough stock). What
            # matters is that a refused movement changed nothing, which
            # the invariant below would catch.
            continue

    await StockService.transfer(
        db_session,
        clinic_id,
        None,
        {
            "item_id": shelf["gloves"].id,
            "from_location_id": shelf["store"].id,
            "to_location_id": shelf["cabinet"].id,
            "lot_id": None,
            "quantity_base": Decimal("25"),
        },
    )
    await db_session.commit()

    ledger = await _ledger_by_triple(db_session, clinic_id)
    levels = await _levels_by_triple(db_session, clinic_id)
    assert levels == ledger, "the snapshot drifted from the ledger"

    # And recomputing from scratch agrees with what was written as it went.
    result = await StockService.reconcile(db_session, clinic_id)
    assert result["corrected"] == 0
    assert result["removed"] == 0


async def test_a_movement_is_never_updated_or_deleted(db_session: AsyncSession) -> None:
    """The append-only rule, read off the source (ADR 0065).

    A rule nobody checks is a convention. Corrections go through a second
    movement, so no code path may update or delete ``inv_movements``.
    """
    offenders = []
    for path in sorted(MODULE_ROOT.rglob("*.py")):
        source = path.read_text()
        for forbidden in ("update(InventoryMovement", "delete(InventoryMovement"):
            if forbidden in source:
                offenders.append(f"{path.name}: {forbidden}")
    assert not offenders, f"the ledger is append-only: {offenders}"


# --- The rules the arithmetic depends on ---------------------------------


async def test_a_lot_tracked_article_refuses_a_movement_without_its_lot(
    db_session: AsyncSession, shelf: dict
) -> None:
    with pytest.raises(InventoryError, match="name the lot"):
        await StockService.post(
            db_session,
            shelf["clinic_id"],
            None,
            item_id=shelf["articaine"].id,
            location_id=shelf["store"].id,
            lot_id=None,
            quantity_base=Decimal("5"),
            reason="purchase_receipt",
        )


async def test_an_article_without_lots_refuses_one(db_session: AsyncSession, shelf: dict) -> None:
    with pytest.raises(InventoryError, match="does not track lots"):
        await StockService.post(
            db_session,
            shelf["clinic_id"],
            None,
            item_id=shelf["gloves"].id,
            location_id=shelf["store"].id,
            lot_id=shelf["lot"].id,
            quantity_base=Decimal("5"),
            reason="purchase_receipt",
        )


async def test_stock_goes_negative_only_through_an_adjustment(
    db_session: AsyncSession, shelf: dict
) -> None:
    """A count may find less than the system believed; a consumption may not.

    Refusing the adjustment too would make a physical count unrecordable
    whenever it disagrees downwards, which is the case it exists for.
    """
    with pytest.raises(InventoryError, match="Not enough stock"):
        await StockService.post(
            db_session,
            shelf["clinic_id"],
            None,
            item_id=shelf["gloves"].id,
            location_id=shelf["store"].id,
            lot_id=None,
            quantity_base=Decimal("1"),
            reason="consumption",
        )

    movement = await StockService.post(
        db_session,
        shelf["clinic_id"],
        None,
        item_id=shelf["gloves"].id,
        location_id=shelf["store"].id,
        lot_id=None,
        quantity_base=Decimal("-3"),
        reason="adjustment",
        note="Faltaban tres pares en el recuento",
    )
    assert movement.quantity_base == Decimal("-3")


async def test_a_reason_carries_its_own_sign(db_session: AsyncSession, shelf: dict) -> None:
    """A receipt adds and a consumption subtracts, whatever the caller sent."""
    await StockService.post(
        db_session,
        shelf["clinic_id"],
        None,
        item_id=shelf["gloves"].id,
        location_id=shelf["store"].id,
        lot_id=None,
        quantity_base=Decimal("10"),
        reason="purchase_receipt",
    )
    used = await StockService.post(
        db_session,
        shelf["clinic_id"],
        None,
        item_id=shelf["gloves"].id,
        location_id=shelf["store"].id,
        lot_id=None,
        quantity_base=Decimal("4"),
        reason="consumption",
    )
    assert used.quantity_base == Decimal("-4")

    totals = await StockService.item_totals(db_session, shelf["clinic_id"], [shelf["gloves"].id])
    assert totals[shelf["gloves"].id] == Decimal("6")


async def test_a_transfer_is_two_lines_and_leaves_the_total_alone(
    db_session: AsyncSession, shelf: dict
) -> None:
    await StockService.post(
        db_session,
        shelf["clinic_id"],
        None,
        item_id=shelf["gloves"].id,
        location_id=shelf["store"].id,
        lot_id=None,
        quantity_base=Decimal("40"),
        reason="purchase_receipt",
    )
    before = await StockService.item_totals(db_session, shelf["clinic_id"], [shelf["gloves"].id])

    moved = await StockService.transfer(
        db_session,
        shelf["clinic_id"],
        None,
        {
            "item_id": shelf["gloves"].id,
            "from_location_id": shelf["store"].id,
            "to_location_id": shelf["cabinet"].id,
            "lot_id": None,
            "quantity_base": Decimal("15"),
        },
    )
    assert len(moved) == 2
    assert moved[0].source_ref == moved[1].source_ref
    assert moved[0].quantity_base == -moved[1].quantity_base

    after = await StockService.item_totals(db_session, shelf["clinic_id"], [shelf["gloves"].id])
    assert after == before

    lines = await StockService.levels(db_session, shelf["clinic_id"], item_id=shelf["gloves"].id)
    by_location = {line["location_name"]: line["quantity"] for line in lines}
    assert by_location == {"Almacén": Decimal("25"), "Gabinete 1": Decimal("15")}


async def test_a_transfer_needs_two_different_locations(
    db_session: AsyncSession, shelf: dict
) -> None:
    with pytest.raises(InventoryError, match="two different locations"):
        await StockService.transfer(
            db_session,
            shelf["clinic_id"],
            None,
            {
                "item_id": shelf["gloves"].id,
                "from_location_id": shelf["store"].id,
                "to_location_id": shelf["store"].id,
                "lot_id": None,
                "quantity_base": Decimal("1"),
            },
        )


async def test_a_count_posts_only_the_differences(db_session: AsyncSession, shelf: dict) -> None:
    """What the brief calls criterion 3: the count is honest about itself."""
    await StockService.post(
        db_session,
        shelf["clinic_id"],
        None,
        item_id=shelf["gloves"].id,
        location_id=shelf["store"].id,
        lot_id=None,
        quantity_base=Decimal("30"),
        reason="purchase_receipt",
    )

    result = await StockService.count(
        db_session,
        shelf["clinic_id"],
        None,
        {
            "lines": [
                # Agrees: posts nothing.
                {
                    "item_id": shelf["gloves"].id,
                    "location_id": shelf["cabinet"].id,
                    "lot_id": None,
                    "counted_quantity": Decimal("0"),
                },
                # Two pairs missing from the shelf.
                {
                    "item_id": shelf["gloves"].id,
                    "location_id": shelf["store"].id,
                    "lot_id": None,
                    "counted_quantity": Decimal("28"),
                },
            ],
            "note": "Recuento del viernes",
        },
    )
    assert result["lines_counted"] == 2
    assert result["adjustments_posted"] == 1

    totals = await StockService.item_totals(db_session, shelf["clinic_id"], [shelf["gloves"].id])
    assert totals[shelf["gloves"].id] == Decimal("28")

    movements, _total = await StockService.movements(
        db_session, shelf["clinic_id"], reason="adjustment"
    )
    assert movements[0].quantity_base == Decimal("-2")
    assert movements[0].note == "Recuento del viernes"


# --- Signals --------------------------------------------------------------


async def test_running_low_and_running_out_are_announced(
    db_session: AsyncSession, shelf: dict
) -> None:
    """The useful moment is the one where the last box leaves the shelf."""
    low: list[dict] = []
    out: list[dict] = []
    event_bus.subscribe(EventType.INVENTORY_STOCK_LOW, low.append)
    event_bus.subscribe(EventType.INVENTORY_STOCK_OUT, out.append)

    await StockService.post(
        db_session,
        shelf["clinic_id"],
        None,
        item_id=shelf["gloves"].id,
        location_id=shelf["store"].id,
        lot_id=None,
        quantity_base=Decimal("25"),
        reason="purchase_receipt",
    )
    await db_session.commit()
    assert low == []

    # Reorder point is 20: taking six pairs crosses it.
    await StockService.post(
        db_session,
        shelf["clinic_id"],
        None,
        item_id=shelf["gloves"].id,
        location_id=shelf["store"].id,
        lot_id=None,
        quantity_base=Decimal("6"),
        reason="consumption",
    )
    await db_session.commit()
    assert [event["item_name"] for event in low] == ["Guantes nitrilo M"]
    assert low[0]["on_hand"] == "19.000"
    assert out == []

    await StockService.post(
        db_session,
        shelf["clinic_id"],
        None,
        item_id=shelf["gloves"].id,
        location_id=shelf["store"].id,
        lot_id=None,
        quantity_base=Decimal("19"),
        reason="consumption",
    )
    await db_session.commit()
    assert [event["item_name"] for event in out] == ["Guantes nitrilo M"]


async def test_an_expiring_lot_is_listed_before_it_expires(
    db_session: AsyncSession, shelf: dict
) -> None:
    from datetime import UTC, datetime, timedelta

    soon = (datetime.now(UTC) + timedelta(days=10)).date()
    lot = await LotService.create(
        db_session,
        shelf["clinic_id"],
        shelf["articaine"].id,
        {"lot_code": "L-CADUCA", "expires_on": soon},
    )
    await StockService.post(
        db_session,
        shelf["clinic_id"],
        None,
        item_id=shelf["articaine"].id,
        location_id=shelf["store"].id,
        lot_id=lot.id,
        quantity_base=Decimal("50"),
        reason="purchase_receipt",
    )
    await db_session.commit()

    alerts = await StockService.alerts(db_session, shelf["clinic_id"])
    assert [line["lot_code"] for line in alerts["expiring"]] == ["L-CADUCA"]
    assert alerts["expiring"][0]["days_to_expiry"] == 10
    assert alerts["expired"] == []


# --- Multi-tenancy --------------------------------------------------------


async def test_one_clinic_never_sees_another_clinics_shelf(
    db_session: AsyncSession, shelf: dict
) -> None:
    other = Clinic(
        id=uuid4(),
        name="Otra Clínica",
        tax_id="B99999999",
        address={"street": "Otra", "city": "Valencia"},
        settings={},
        account_tier="clinic",
    )
    db_session.add(other)
    await db_session.flush()

    their_item = await ItemService.create(
        db_session,
        other.id,
        {"code": "GUA-100", "name": "Guantes de la otra", "base_unit": "par"},
    )
    their_location = await LocationService.create(
        db_session, other.id, {"name": "Almacén", "kind": "warehouse", "is_default": True}
    )
    await StockService.post(
        db_session,
        other.id,
        None,
        item_id=their_item.id,
        location_id=their_location.id,
        lot_id=None,
        quantity_base=Decimal("99"),
        reason="purchase_receipt",
    )
    await db_session.commit()

    # The same code in both clinics is fine, and neither sees the other.
    mine, total = await ItemService.list(db_session, shelf["clinic_id"])
    assert total == 2
    assert their_item.id not in {item.id for item in mine}

    lines = await StockService.levels(db_session, shelf["clinic_id"])
    assert all(line["quantity"] != Decimal("99") for line in lines)

    assert await ItemService.get(db_session, shelf["clinic_id"], their_item.id) is None

    # ...and a movement cannot be posted across the boundary.
    with pytest.raises(InventoryError, match="Article not found"):
        await StockService.post(
            db_session,
            shelf["clinic_id"],
            None,
            item_id=their_item.id,
            location_id=shelf["store"].id,
            lot_id=None,
            quantity_base=Decimal("1"),
            reason="consumption",
        )


async def test_archiving_keeps_the_history(db_session: AsyncSession, shelf: dict) -> None:
    """An article is archived, never deleted: the ledger still names it."""
    await StockService.post(
        db_session,
        shelf["clinic_id"],
        None,
        item_id=shelf["gloves"].id,
        location_id=shelf["store"].id,
        lot_id=None,
        quantity_base=Decimal("5"),
        reason="purchase_receipt",
    )
    await ItemService.archive(db_session, shelf["clinic_id"], shelf["gloves"].id)
    await db_session.commit()

    item = await db_session.scalar(
        select(InventoryItem).where(InventoryItem.id == shelf["gloves"].id)
    )
    assert item is not None
    assert item.status == "archived"

    movements, total = await StockService.movements(
        db_session, shelf["clinic_id"], item_id=shelf["gloves"].id
    )
    assert total == 1
    assert movements[0].item.name == "Guantes nitrilo M"
