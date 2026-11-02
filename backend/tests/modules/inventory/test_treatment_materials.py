"""Layer 3: what a treatment consumes, and what happens when it is done.

The mechanism is deliberately one-way. `treatment_plan` announces that
an item was completed — a fact about its own world — and the inventory
listens. Nothing reads the inventory, nothing imports it, and with this
module off the event simply goes unanswered (ADR 0064).

What is pinned here is the behaviour that is easy to get wrong: posting
once per planned item however many times the event arrives, consuming
what there is rather than inventing a negative, and leaving lot-tracked
material to a human.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.inventory.events import consume_for_treatment, on_treatment_completed
from app.modules.inventory.models import (
    InventoryMovement,
    InventoryStockLevel,
    TreatmentMaterial,
)
from app.modules.inventory.service import (
    ItemService,
    LocationService,
    MaterialService,
    StockService,
)


@pytest.fixture
async def shelf(db_session: AsyncSession, test_clinic: Clinic) -> dict:
    """An article with stock, a lot-tracked one, and a place to keep them."""
    store = await LocationService.create(
        db_session, test_clinic.id, {"name": "Almacén", "kind": "warehouse", "is_default": True}
    )
    gloves = await ItemService.create(
        db_session,
        test_clinic.id,
        {"code": "GUA-NIT-M", "name": "Guantes", "base_unit": "par"},
    )
    anaesthetic = await ItemService.create(
        db_session,
        test_clinic.id,
        {
            "code": "ANE-ART",
            "name": "Articaína",
            "base_unit": "carpule",
            "tracks_lots": True,
        },
    )
    await StockService.post(
        db_session,
        test_clinic.id,
        None,
        item_id=gloves.id,
        location_id=store.id,
        lot_id=None,
        quantity_base=Decimal("100"),
        reason="purchase_receipt",
    )
    await db_session.commit()
    return {
        "clinic_id": test_clinic.id,
        "gloves": gloves,
        "anaesthetic": anaesthetic,
        "store": store,
    }


def _event(clinic_id, item_id, **overrides) -> dict:
    """The payload `treatment_plan` publishes, as it publishes it."""
    data = {
        "clinic_id": str(clinic_id),
        "item_id": str(item_id),
        "plan_id": str(uuid4()),
        "treatment_id": str(uuid4()),
        "patient_id": str(uuid4()),
        "completed_by": None,
        "item_name": "Obturación composite",
        "occurred_at": None,
        "treatment_category_key": None,
    }
    data.update(overrides)
    return data


class _Directory:
    """Stands in for the `PlannedTreatments` contract.

    The real one belongs to `treatment_plan`, which this module does not
    import and must not need in a test either.
    """

    def __init__(self, mapping: dict):
        self._mapping = mapping

    async def catalog_item_ids(self, db, clinic_id, item_ids):
        return {item_id: self._mapping.get(item_id) for item_id in item_ids}


@pytest.fixture
def with_directory(monkeypatch):
    def install(mapping: dict):
        monkeypatch.setattr(
            "app.modules.inventory.events.planned_treatments", lambda: _Directory(mapping)
        )

    return install


# --- the materials list --------------------------------------------------


async def test_a_treatments_list_is_written_whole(db_session: AsyncSession, shelf: dict) -> None:
    treatment = uuid4()
    await MaterialService.set_for_treatment(
        db_session,
        shelf["clinic_id"],
        treatment,
        [{"item_id": shelf["gloves"].id, "quantity_base": Decimal("2")}],
    )
    await db_session.commit()

    # Writing it again replaces, rather than appending a second line.
    rows = await MaterialService.set_for_treatment(
        db_session,
        shelf["clinic_id"],
        treatment,
        [{"item_id": shelf["gloves"].id, "quantity_base": Decimal("3")}],
    )
    await db_session.commit()

    assert len(rows) == 1
    assert rows[0].quantity_base == Decimal("3.000")

    total = await db_session.scalar(
        select(func.count())
        .select_from(TreatmentMaterial)
        .where(TreatmentMaterial.clinic_id == shelf["clinic_id"])
    )
    assert total == 1


async def test_an_empty_list_clears_the_treatment(db_session: AsyncSession, shelf: dict) -> None:
    treatment = uuid4()
    await MaterialService.set_for_treatment(
        db_session,
        shelf["clinic_id"],
        treatment,
        [{"item_id": shelf["gloves"].id, "quantity_base": Decimal("2")}],
    )
    await db_session.commit()

    assert (
        await MaterialService.set_for_treatment(db_session, shelf["clinic_id"], treatment, []) == []
    )


# --- automatic consumption -----------------------------------------------


async def test_completing_a_treatment_takes_its_material_off_the_shelf(
    db_session: AsyncSession, shelf: dict, with_directory
) -> None:
    treatment, planned_item = uuid4(), uuid4()
    with_directory({planned_item: treatment})
    await MaterialService.set_for_treatment(
        db_session,
        shelf["clinic_id"],
        treatment,
        [{"item_id": shelf["gloves"].id, "quantity_base": Decimal("2")}],
    )
    await db_session.commit()

    await consume_for_treatment(_event(shelf["clinic_id"], planned_item), db_session)
    await db_session.commit()

    totals = await StockService.item_totals(db_session, shelf["clinic_id"], [shelf["gloves"].id])
    assert totals[shelf["gloves"].id] == Decimal("98")

    movements, _total = await StockService.movements(
        db_session, shelf["clinic_id"], reason="consumption"
    )
    assert movements[0].quantity_base == Decimal("-2.000")
    assert movements[0].note == "Obturación composite"
    # Opaque, and what makes a second delivery of the event a no-op.
    assert movements[0].source_ref == {"kind": "treatment_item", "id": str(planned_item)}


async def test_the_same_treatment_never_consumes_twice(
    db_session: AsyncSession, shelf: dict, with_directory
) -> None:
    """Events get redelivered, and an item can be reopened and completed
    again. The material was used once."""
    treatment, planned_item = uuid4(), uuid4()
    with_directory({planned_item: treatment})
    await MaterialService.set_for_treatment(
        db_session,
        shelf["clinic_id"],
        treatment,
        [{"item_id": shelf["gloves"].id, "quantity_base": Decimal("2")}],
    )
    await db_session.commit()

    for _ in range(3):
        await consume_for_treatment(_event(shelf["clinic_id"], planned_item), db_session)
        await db_session.commit()

    totals = await StockService.item_totals(db_session, shelf["clinic_id"], [shelf["gloves"].id])
    assert totals[shelf["gloves"].id] == Decimal("98")


async def test_a_shortfall_consumes_what_there_is_and_says_so(
    db_session: AsyncSession, shelf: dict, with_directory
) -> None:
    """The treatment happened. Writing a negative would break the
    ledger's invariant; refusing would throw away the fact."""
    treatment, planned_item = uuid4(), uuid4()
    with_directory({planned_item: treatment})
    await MaterialService.set_for_treatment(
        db_session,
        shelf["clinic_id"],
        treatment,
        [{"item_id": shelf["gloves"].id, "quantity_base": Decimal("150")}],
    )
    await db_session.commit()

    await consume_for_treatment(_event(shelf["clinic_id"], planned_item), db_session)
    await db_session.commit()

    totals = await StockService.item_totals(db_session, shelf["clinic_id"], [shelf["gloves"].id])
    assert totals[shelf["gloves"].id] == Decimal("0")

    movements, _total = await StockService.movements(
        db_session, shelf["clinic_id"], reason="consumption"
    )
    assert movements[0].quantity_base == Decimal("-100.000")
    assert "faltaban 50" in movements[0].note

    levels = await db_session.execute(
        select(InventoryStockLevel.quantity).where(
            InventoryStockLevel.clinic_id == shelf["clinic_id"]
        )
    )
    assert all(Decimal(q) >= 0 for (q,) in levels.all())


async def test_lot_tracked_material_is_left_to_a_human(
    db_session: AsyncSession, shelf: dict, with_directory
) -> None:
    """Which batch was opened is a fact only the person at the chair
    knows, so the handler skips it rather than guessing."""
    treatment, planned_item = uuid4(), uuid4()
    with_directory({planned_item: treatment})
    await MaterialService.set_for_treatment(
        db_session,
        shelf["clinic_id"],
        treatment,
        [
            {"item_id": shelf["gloves"].id, "quantity_base": Decimal("2")},
            {"item_id": shelf["anaesthetic"].id, "quantity_base": Decimal("1")},
        ],
    )
    await db_session.commit()

    await consume_for_treatment(_event(shelf["clinic_id"], planned_item), db_session)
    await db_session.commit()

    # The rest of the treatment's material still moved.
    totals = await StockService.item_totals(db_session, shelf["clinic_id"], [shelf["gloves"].id])
    assert totals[shelf["gloves"].id] == Decimal("98")

    anaesthetic_movements = await db_session.scalar(
        select(func.count())
        .select_from(InventoryMovement)
        .where(InventoryMovement.item_id == shelf["anaesthetic"].id)
    )
    assert anaesthetic_movements == 0


async def test_a_treatment_with_no_list_consumes_nothing(
    db_session: AsyncSession, shelf: dict, with_directory
) -> None:
    planned_item = uuid4()
    with_directory({planned_item: uuid4()})

    await consume_for_treatment(_event(shelf["clinic_id"], planned_item), db_session)
    await db_session.commit()

    movements, total = await StockService.movements(
        db_session, shelf["clinic_id"], reason="consumption"
    )
    assert total == 0
    assert movements == []


async def test_the_bus_can_call_the_handler_with_only_the_payload(
    db_session: AsyncSession, shelf: dict, with_directory
) -> None:
    """How the event bus actually calls it: one argument, no session.

    The first version took ``db`` as a parameter. Every unit test passed
    — they called it directly — and in the running app it raised
    ``missing 1 required positional argument: 'db'`` on the first
    completed treatment, which the bus swallowed into a logged failure.
    """
    import inspect

    signature = inspect.signature(on_treatment_completed)
    assert list(signature.parameters) == ["data"]
