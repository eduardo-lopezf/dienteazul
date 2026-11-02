"""Layer 5: what the material actually cost.

The inventory's first outward contract. Two things are pinned: that a
cost is read from what the ledger recorded **when the movement
happened**, so a report of last March does not change next year; and
that the figure only counts what was really consumed.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.contracts import MaterialCost, MaterialCostLine
from app.modules.inventory.providers import material_cost
from app.modules.inventory.service import (
    ItemService,
    LocationService,
    StockService,
)

TODAY = date.today()
WINDOW = (TODAY - timedelta(days=1), TODAY + timedelta(days=1))


class _Directory:
    """Stands in for `PlannedTreatments`, which belongs to another App."""

    def __init__(self, mapping: dict):
        self._mapping = mapping

    async def catalog_item_ids(self, db, clinic_id, item_ids):
        return {item_id: self._mapping.get(item_id) for item_id in item_ids}


@pytest.fixture
def with_directory(monkeypatch):
    def install(mapping: dict):
        monkeypatch.setattr(
            "app.modules.inventory.providers.planned_treatments", lambda: _Directory(mapping)
        )

    return install


@pytest.fixture
async def shelf(db_session: AsyncSession, test_clinic: Clinic) -> dict:
    store = await LocationService.create(
        db_session, test_clinic.id, {"name": "Almacén", "kind": "warehouse", "is_default": True}
    )
    gloves = await ItemService.create(
        db_session,
        test_clinic.id,
        {
            "code": "GUA",
            "name": "Guantes",
            "base_unit": "par",
            "cost_per_base_unit": Decimal("0.10"),
        },
    )
    await StockService.post(
        db_session,
        test_clinic.id,
        None,
        item_id=gloves.id,
        location_id=store.id,
        lot_id=None,
        quantity_base=Decimal("1000"),
        reason="purchase_receipt",
        cost_per_base_unit=Decimal("0.10"),
    )
    await db_session.commit()
    return {"clinic_id": test_clinic.id, "gloves": gloves, "store": store}


async def _consume(db, clinic_id, item_id, quantity, planned_item: UUID) -> None:
    await StockService.post(
        db,
        clinic_id,
        None,
        item_id=item_id,
        location_id=None,
        lot_id=None,
        quantity_base=Decimal(quantity),
        reason="consumption",
        source_ref={"kind": "treatment_item", "id": str(planned_item)},
    )


# --- the figures ---------------------------------------------------------


async def test_cost_is_grouped_by_treatment_type(
    db_session: AsyncSession, shelf: dict, with_directory
) -> None:
    obturacion, endodoncia = uuid4(), uuid4()
    first, second, third = uuid4(), uuid4(), uuid4()
    with_directory({first: obturacion, second: obturacion, third: endodoncia})

    await _consume(db_session, shelf["clinic_id"], shelf["gloves"].id, "10", first)
    await _consume(db_session, shelf["clinic_id"], shelf["gloves"].id, "10", second)
    await _consume(db_session, shelf["clinic_id"], shelf["gloves"].id, "4", third)
    await db_session.commit()

    lines = await material_cost.by_treatment(db_session, shelf["clinic_id"], *WINDOW)

    assert [line.catalog_item_id for line in lines] == [obturacion, endodoncia]
    assert lines[0] == MaterialCostLine(
        catalog_item_id=obturacion, treatments=2, cost=Decimal("2.00")
    )
    assert lines[1].cost == Decimal("0.40")


async def test_the_cost_is_the_one_recorded_at_the_time(
    db_session: AsyncSession, shelf: dict, with_directory
) -> None:
    """A report of a past period must not move when prices change.

    The ledger stamps what a movement cost when it happened; re-pricing
    the article afterwards changes what the *next* consumption costs and
    nothing already recorded.
    """
    treatment, planned = uuid4(), uuid4()
    with_directory({planned: treatment})
    await _consume(db_session, shelf["clinic_id"], shelf["gloves"].id, "10", planned)
    await db_session.commit()

    before = await material_cost.by_treatment(db_session, shelf["clinic_id"], *WINDOW)
    assert before[0].cost == Decimal("1.00")

    await ItemService.update(
        db_session,
        shelf["clinic_id"],
        shelf["gloves"].id,
        {"cost_per_base_unit": Decimal("0.50")},
    )
    await db_session.commit()

    after = await material_cost.by_treatment(db_session, shelf["clinic_id"], *WINDOW)
    assert after[0].cost == Decimal("1.00")


async def test_transfers_and_adjustments_are_not_a_cost(
    db_session: AsyncSession, shelf: dict, with_directory
) -> None:
    """Moving stock between shelves costs nothing, and a correction is
    not consumption."""
    with_directory({})
    other = await LocationService.create(
        db_session, shelf["clinic_id"], {"name": "Gabinete 1", "kind": "cabinet"}
    )
    await StockService.transfer(
        db_session,
        shelf["clinic_id"],
        None,
        {
            "item_id": shelf["gloves"].id,
            "from_location_id": shelf["store"].id,
            "to_location_id": other.id,
            "lot_id": None,
            "quantity_base": Decimal("100"),
        },
    )
    await StockService.post(
        db_session,
        shelf["clinic_id"],
        None,
        item_id=shelf["gloves"].id,
        location_id=shelf["store"].id,
        lot_id=None,
        quantity_base=Decimal("-5"),
        reason="adjustment",
        note="Recuento",
    )
    await db_session.commit()

    assert await material_cost.consumed_total(db_session, shelf["clinic_id"], *WINDOW) == Decimal(
        "0.00"
    )


async def test_an_expiry_write_off_is_a_cost(
    db_session: AsyncSession, shelf: dict, with_directory
) -> None:
    """Material thrown away was paid for: it belongs in the figure, even
    though no treatment used it."""
    with_directory({})
    await StockService.post(
        db_session,
        shelf["clinic_id"],
        None,
        item_id=shelf["gloves"].id,
        location_id=shelf["store"].id,
        lot_id=None,
        quantity_base=Decimal("20"),
        reason="expiry_write_off",
    )
    await db_session.commit()

    total = await material_cost.consumed_total(db_session, shelf["clinic_id"], *WINDOW)
    assert total == Decimal("2.00")
    # ...and it is not attributed to any treatment.
    assert await material_cost.by_treatment(db_session, shelf["clinic_id"], *WINDOW) == []


async def test_material_with_no_price_counts_as_nothing_rather_than_a_guess(
    db_session: AsyncSession, test_clinic: Clinic, with_directory
) -> None:
    await LocationService.create(
        db_session, test_clinic.id, {"name": "Almacén", "kind": "warehouse", "is_default": True}
    )
    unpriced = await ItemService.create(
        db_session, test_clinic.id, {"code": "X", "name": "Sin precio", "base_unit": "unidad"}
    )
    await StockService.post(
        db_session,
        test_clinic.id,
        None,
        item_id=unpriced.id,
        location_id=None,
        lot_id=None,
        quantity_base=Decimal("50"),
        reason="purchase_receipt",
    )
    treatment, planned = uuid4(), uuid4()
    with_directory({planned: treatment})
    await _consume(db_session, test_clinic.id, unpriced.id, "5", planned)
    await db_session.commit()

    lines = await material_cost.by_treatment(db_session, test_clinic.id, *WINDOW)
    assert lines[0].cost == Decimal("0")
    assert lines[0].treatments == 1
    # ...and the line says so, so a consumer never reads the zero as
    # "this treatment is free".
    assert lines[0].unpriced == 1


async def test_one_clinic_never_sees_another_clinics_cost(
    db_session: AsyncSession, shelf: dict, with_directory
) -> None:
    other = Clinic(
        id=uuid4(), name="Otra", tax_id="B9", address={}, settings={}, account_tier="clinic"
    )
    db_session.add(other)
    await db_session.flush()
    planned = uuid4()
    with_directory({planned: uuid4()})
    await _consume(db_session, shelf["clinic_id"], shelf["gloves"].id, "10", planned)
    await db_session.commit()

    assert await material_cost.consumed_total(db_session, other.id, *WINDOW) == Decimal("0.00")


def test_the_module_supplies_the_contract() -> None:
    from app.core.plugins.registry import module_registry

    providers = module_registry.get("inventory").get_providers()
    assert MaterialCost in providers
