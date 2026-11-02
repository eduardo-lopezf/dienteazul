"""The Inventario App runs with everything it reads switched off (ADR 0037).

Layer 3 gave the inventory two links outward — the treatment catalogue
and planned treatments — and both are contracts, not imports. This file
is the executable form of the promise that came with them:

- the App requires no other App, and declares no `integrates`, because
  it has no foreign key into one;
- with Treatments off, the materials lists keep their rows and lose only
  the names, the picker is honestly empty, and stock, movements and
  alerts are untouched;
- nothing else reads the inventory, so switching *it* off is somebody
  else's no-op.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.plugins.registry import module_registry
from app.modules.inventory.events import consume_for_treatment
from app.modules.inventory.service import (
    ItemService,
    LocationService,
    MaterialService,
    StockService,
)

BASE = "/api/v1/inventory"

#: The modules whose data the inventory reads, and through what.
#: `catalog` supplies `TreatmentCatalogue`, `treatment_plan` supplies
#: `PlannedTreatments`. Neither is imported and neither is a dependency.
READS_THROUGH_CONTRACTS = {"catalog", "treatment_plan"}


@contextmanager
def off(*names: str) -> Iterator[None]:
    was_active = [name for name in names if module_registry.is_installed(name)]
    for name in names:
        module_registry.deactivate(name)
    try:
        yield
    finally:
        for name in was_active:
            module_registry.activate(name)


def test_the_inventory_requires_none_of_what_it_reads() -> None:
    manifest = module_registry.get("inventory").manifest
    assert manifest["depends"] == []
    # `integrates` lists the owners of tables this module's foreign keys
    # point at. There are none: `catalog_item_id` is a plain column on
    # purpose, so that Treatments can be switched off.
    assert manifest["integrates"] == []


def test_nothing_imports_the_inventory() -> None:
    """The direction of the coupling, read off the source.

    `purchasing` is the one module allowed to, and it is in the same App
    and declares it in `depends`. Anything else importing the inventory
    would make the App impossible to switch off.
    """
    from pathlib import Path

    modules_root = Path(__file__).resolve().parents[1] / "app" / "modules"
    offenders = []
    for path in sorted(modules_root.rglob("*.py")):
        owner = path.relative_to(modules_root).parts[0]
        if owner in ("inventory", "purchasing") or "/migrations/" in str(path):
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if "app.modules.inventory" in line:
                offenders.append(f"{path.relative_to(modules_root)}:{number}")
    assert not offenders, f"these would weld the inventory in place: {offenders}"


@pytest.fixture
async def shelf(db_session: AsyncSession, test_clinic: Clinic) -> dict:
    store = await LocationService.create(
        db_session, test_clinic.id, {"name": "Almacén", "kind": "warehouse", "is_default": True}
    )
    gloves = await ItemService.create(
        db_session, test_clinic.id, {"code": "GUA", "name": "Guantes", "base_unit": "par"}
    )
    await StockService.post(
        db_session,
        test_clinic.id,
        None,
        item_id=gloves.id,
        location_id=store.id,
        lot_id=None,
        quantity_base=Decimal("50"),
        reason="purchase_receipt",
    )
    treatment = uuid4()
    await MaterialService.set_for_treatment(
        db_session,
        test_clinic.id,
        treatment,
        [{"item_id": gloves.id, "quantity_base": Decimal("2")}],
    )
    await db_session.commit()
    return {"clinic_id": test_clinic.id, "gloves": gloves, "treatment": treatment}


async def test_with_treatments_off_the_lists_keep_their_rows_and_lose_the_names(
    client: AsyncClient, auth_headers: dict, shelf: dict
) -> None:
    with off("catalog"):
        listed = await client.get(f"{BASE}/materials", headers=auth_headers)
        assert listed.status_code == 200
        row = listed.json()["data"][0]
        assert row["catalog_item_id"] == str(shelf["treatment"])
        assert row["lines"][0]["item_code"] == "GUA"
        # The ids are ours; the names are not.
        assert row["treatment_name"] is None
        assert row["treatment_code"] is None

        # And there is nothing honest to offer in the picker.
        options = await client.get(f"{BASE}/materials/treatments", headers=auth_headers)
        assert options.json()["data"] == []


async def test_with_treatments_off_stock_is_untouched(
    client: AsyncClient, auth_headers: dict, shelf: dict
) -> None:
    with off("catalog", "treatment_plan"):
        stock = await client.get(f"{BASE}/stock", headers=auth_headers)
        assert stock.json()["data"][0]["quantity"] == "50.000"

        movements = await client.get(f"{BASE}/movements", headers=auth_headers)
        assert movements.json()["total"] == 1

        alerts = await client.get(f"{BASE}/stock/alerts", headers=auth_headers)
        assert alerts.status_code == 200

        # A receipt still works: nothing in the write path asks about
        # treatments.
        posted = await client.post(
            f"{BASE}/movements",
            json={
                "item_id": str(shelf["gloves"].id),
                "quantity_base": "10",
                "reason": "purchase_receipt",
            },
            headers=auth_headers,
        )
        assert posted.status_code == 201


async def test_with_treatment_plan_off_nothing_is_consumed_and_nothing_breaks(
    db_session: AsyncSession, shelf: dict
) -> None:
    """The handler can outlive its publisher in a process being
    reconfigured. It asks the contract and finds nobody."""
    with off("treatment_plan"):
        await consume_for_treatment(
            {
                "clinic_id": str(shelf["clinic_id"]),
                "item_id": str(uuid4()),
                "item_name": "Obturación",
                "completed_by": None,
            },
            db_session,
        )
        await db_session.commit()

    totals = await StockService.item_totals(db_session, shelf["clinic_id"], [shelf["gloves"].id])
    assert totals[shelf["gloves"].id] == Decimal("50")


def test_the_contracts_it_reads_are_supplied_by_the_modules_named_here() -> None:
    """Keeps `READS_THROUGH_CONTRACTS` honest as the module grows."""
    from app.core.contracts import PlannedTreatments, TreatmentCatalogue

    suppliers = {
        name
        for name in READS_THROUGH_CONTRACTS
        if {TreatmentCatalogue, PlannedTreatments} & set(module_registry.get(name).get_providers())
    }
    assert suppliers == READS_THROUGH_CONTRACTS


# --- the one thing that flows outward -----------------------------------


async def test_productividad_keeps_working_with_the_inventory_off(
    client: AsyncClient, auth_headers: dict, shelf: dict
) -> None:
    """Layer 5 is the first time anything reads the inventory.

    `reports` asks for the `MaterialCost` contract and must never import
    the module. With the App off the section answers 404 and every other
    report is untouched — which is the whole promise of a switchable App
    (ADR 0037).
    """
    from datetime import date, timedelta

    window = f"date_from={date.today() - timedelta(days=1)}&date_to={date.today()}"

    live = await client.get(f"/api/v1/reports/materials/cost?{window}", headers=auth_headers)
    assert live.status_code == 200

    with off("inventory"):
        gone = await client.get(f"/api/v1/reports/materials/cost?{window}", headers=auth_headers)
        assert gone.status_code == 404

        # ...and the rest of Productividad is still there.
        scheduling = await client.get(
            f"/api/v1/reports/scheduling/summary?{window}", headers=auth_headers
        )
        assert scheduling.status_code == 200


def test_reports_integrates_the_inventory_and_does_not_depend_on_it() -> None:
    manifest = module_registry.get("reports").manifest
    assert "inventory" in manifest["integrates"]
    assert "inventory" not in manifest["depends"]
