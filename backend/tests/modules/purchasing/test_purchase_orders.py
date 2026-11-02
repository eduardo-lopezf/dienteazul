"""Buying things, and what reaches the stock ledger when they arrive.

The rule under test is the one that keeps the inventory honest: a
delivery is not a number somebody types into stock, it is movements
posted through ``StockService`` (ADR 0065). So after any receipt the
ledger still equals the snapshot, and each movement carries the price
paid and a `source_ref` naming the order line that caused it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.inventory.models import InventoryItem, InventoryMovement, InventoryStockLevel
from app.modules.inventory.service import StockService

BASE = "/api/v1/purchasing"
INVENTORY = "/api/v1/inventory"


async def _supplier(client: AsyncClient, headers: dict, name: str = "Dental Supplies SL") -> dict:
    response = await client.post(
        f"{BASE}/suppliers",
        json={"name": name, "tax_id": "B12345678", "email": "pedidos@example.com"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _item(client: AsyncClient, headers: dict, **overrides) -> dict:
    body = {
        "code": "GUA-NIT-M",
        "name": "Guantes de nitrilo talla M",
        "base_unit": "par",
        "category": "consumable",
    }
    body.update(overrides)
    response = await client.post(f"{INVENTORY}/items", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _order(client: AsyncClient, headers: dict, supplier: dict, lines: list[dict]) -> dict:
    response = await client.post(
        f"{BASE}/orders",
        json={
            "supplier_id": supplier["id"],
            "order_date": date.today().isoformat(),
            "lines": lines,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _ledger_matches_snapshot(db: AsyncSession, clinic_id) -> bool:
    ledger = await db.execute(
        select(
            InventoryMovement.item_id,
            InventoryMovement.location_id,
            InventoryMovement.lot_id,
            func.sum(InventoryMovement.quantity_base),
        )
        .where(InventoryMovement.clinic_id == clinic_id)
        .group_by(
            InventoryMovement.item_id, InventoryMovement.location_id, InventoryMovement.lot_id
        )
    )
    truth = {(i, loc, lot): Decimal(total) for i, loc, lot, total in ledger.all()}
    rows = await db.execute(
        select(InventoryStockLevel).where(InventoryStockLevel.clinic_id == clinic_id)
    )
    levels = {
        (lvl.item_id, lvl.location_id, lvl.lot_id): Decimal(lvl.quantity)
        for lvl in rows.scalars().all()
    }
    return truth == levels


# --- the order's own life ------------------------------------------------


async def test_an_order_is_numbered_per_clinic_and_per_year(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    supplier = await _supplier(client, auth_headers)
    item = await _item(client, auth_headers)
    line = {"item_id": item["id"], "quantity_ordered": "400", "unit_cost": "0.12"}

    first = await _order(client, auth_headers, supplier, [line])
    second = await _order(client, auth_headers, supplier, [line])

    year = date.today().year
    assert first["number"] == f"P-{year}-0001"
    assert second["number"] == f"P-{year}-0002"
    assert first["total"] == "48.00"


async def test_a_sent_order_can_no_longer_be_rewritten(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """What was sent is what the supplier was told."""
    supplier = await _supplier(client, auth_headers)
    item = await _item(client, auth_headers)
    order = await _order(
        client,
        auth_headers,
        supplier,
        [{"item_id": item["id"], "quantity_ordered": "100", "unit_cost": "0.12"}],
    )

    edit = await client.put(
        f"{BASE}/orders/{order['id']}",
        json={"notes": "antes de enviar"},
        headers=auth_headers,
    )
    assert edit.status_code == 200

    sent = await client.post(f"{BASE}/orders/{order['id']}/send", headers=auth_headers)
    assert sent.json()["data"]["status"] == "sent"

    refused = await client.put(
        f"{BASE}/orders/{order['id']}", json={"notes": "después"}, headers=auth_headers
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "purchasing.order.not_draft"


# --- receiving -----------------------------------------------------------


async def test_receiving_posts_movements_and_leaves_the_ledger_whole(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic, db_session: AsyncSession
) -> None:
    supplier = await _supplier(client, auth_headers)
    item = await _item(client, auth_headers)
    order = await _order(
        client,
        auth_headers,
        supplier,
        [{"item_id": item["id"], "quantity_ordered": "400", "unit_cost": "0.12"}],
    )
    await client.post(f"{BASE}/orders/{order['id']}/send", headers=auth_headers)

    receipt = await client.post(
        f"{BASE}/orders/{order['id']}/receive",
        json={
            "lines": [{"line_id": order["lines"][0]["id"], "quantity": "400"}],
            "note": "Albarán 5512",
        },
        headers=auth_headers,
    )
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()["data"]["order_status"] == "received"

    stock = await client.get(f"{INVENTORY}/stock", headers=auth_headers)
    assert stock.json()["data"][0]["quantity"] == "400.000"

    movements = await client.get(f"{INVENTORY}/movements", headers=auth_headers)
    movement = movements.json()["data"][0]
    assert movement["reason"] == "purchase_receipt"
    assert movement["cost_per_base_unit"] == "0.1200"
    assert movement["note"] == "Albarán 5512"
    # Opaque, and enough to walk back to the line that caused it.
    assert movement["source_ref"]["kind"] == "purchase_order"
    assert movement["source_ref"]["line"] == order["lines"][0]["id"]

    assert await _ledger_matches_snapshot(db_session, test_clinic.id)


async def test_a_partial_delivery_leaves_the_rest_pending(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """The normal case: a supplier sends what it has."""
    supplier = await _supplier(client, auth_headers)
    item = await _item(client, auth_headers)
    order = await _order(
        client,
        auth_headers,
        supplier,
        [{"item_id": item["id"], "quantity_ordered": "400", "unit_cost": "0.12"}],
    )
    await client.post(f"{BASE}/orders/{order['id']}/send", headers=auth_headers)

    first = await client.post(
        f"{BASE}/orders/{order['id']}/receive",
        json={"lines": [{"line_id": order["lines"][0]["id"], "quantity": "250"}]},
        headers=auth_headers,
    )
    assert first.json()["data"]["order_status"] == "partially_received"

    reloaded = await client.get(f"{BASE}/orders/{order['id']}", headers=auth_headers)
    assert reloaded.json()["data"]["lines"][0]["quantity_pending"] == "150.000"

    rest = await client.post(
        f"{BASE}/orders/{order['id']}/receive",
        json={"lines": [{"line_id": order["lines"][0]["id"], "quantity": "150"}]},
        headers=auth_headers,
    )
    assert rest.json()["data"]["order_status"] == "received"


async def test_receiving_more_than_was_ordered_is_refused(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    supplier = await _supplier(client, auth_headers)
    item = await _item(client, auth_headers)
    order = await _order(
        client,
        auth_headers,
        supplier,
        [{"item_id": item["id"], "quantity_ordered": "100", "unit_cost": "0.12"}],
    )
    await client.post(f"{BASE}/orders/{order['id']}/send", headers=auth_headers)

    response = await client.post(
        f"{BASE}/orders/{order['id']}/receive",
        json={"lines": [{"line_id": order["lines"][0]["id"], "quantity": "120"}]},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "purchasing.receipt.exceeds_pending"


async def test_a_lot_tracked_article_needs_its_lot_on_the_delivery_note(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    supplier = await _supplier(client, auth_headers)
    item = await _item(client, auth_headers, code="ANE-ART", name="Articaína", tracks_lots=True)
    order = await _order(
        client,
        auth_headers,
        supplier,
        [{"item_id": item["id"], "quantity_ordered": "200", "unit_cost": "0.65"}],
    )
    await client.post(f"{BASE}/orders/{order['id']}/send", headers=auth_headers)
    line_id = order["lines"][0]["id"]

    without = await client.post(
        f"{BASE}/orders/{order['id']}/receive",
        json={"lines": [{"line_id": line_id, "quantity": "100"}]},
        headers=auth_headers,
    )
    assert without.status_code == 422
    assert without.json()["code"] == "purchasing.receipt.lot_required"

    # The lot is created from the delivery note, without a detour.
    with_lot = await client.post(
        f"{BASE}/orders/{order['id']}/receive",
        json={
            "lines": [
                {
                    "line_id": line_id,
                    "quantity": "100",
                    "lot_code": "ART-2801",
                    "expires_on": "2028-02-25",
                }
            ]
        },
        headers=auth_headers,
    )
    assert with_lot.status_code == 201, with_lot.text

    lots = await client.get(f"{INVENTORY}/items/{item['id']}/lots", headers=auth_headers)
    assert [lot["lot_code"] for lot in lots.json()["data"]] == ["ART-2801"]
    assert lots.json()["data"][0]["expires_on"] == "2028-02-25"


# --- cost ----------------------------------------------------------------


async def test_the_article_cost_is_a_weighted_average(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic, db_session: AsyncSession
) -> None:
    """Buying 100 at a new price does not reprice what is already there."""
    supplier = await _supplier(client, auth_headers)
    item = await _item(client, auth_headers)

    first = await _order(
        client,
        auth_headers,
        supplier,
        [{"item_id": item["id"], "quantity_ordered": "100", "unit_cost": "0.10"}],
    )
    await client.post(f"{BASE}/orders/{first['id']}/send", headers=auth_headers)
    await client.post(
        f"{BASE}/orders/{first['id']}/receive",
        json={"lines": [{"line_id": first["lines"][0]["id"], "quantity": "100"}]},
        headers=auth_headers,
    )

    second = await _order(
        client,
        auth_headers,
        supplier,
        [{"item_id": item["id"], "quantity_ordered": "100", "unit_cost": "0.20"}],
    )
    await client.post(f"{BASE}/orders/{second['id']}/send", headers=auth_headers)
    await client.post(
        f"{BASE}/orders/{second['id']}/receive",
        json={"lines": [{"line_id": second["lines"][0]["id"], "quantity": "100"}]},
        headers=auth_headers,
    )

    stored = await db_session.scalar(
        select(InventoryItem.cost_per_base_unit).where(InventoryItem.id == item["id"])
    )
    assert Decimal(stored) == Decimal("0.1500")

    # And the ledger keeps what each delivery actually cost.
    movements = await client.get(f"{INVENTORY}/movements", headers=auth_headers)
    assert [m["cost_per_base_unit"] for m in movements.json()["data"]] == ["0.2000", "0.1000"]


# --- suppliers -----------------------------------------------------------


async def test_a_supplier_with_goods_on_the_way_cannot_be_archived(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    supplier = await _supplier(client, auth_headers)
    item = await _item(client, auth_headers)
    order = await _order(
        client,
        auth_headers,
        supplier,
        [{"item_id": item["id"], "quantity_ordered": "100", "unit_cost": "0.12"}],
    )
    await client.post(f"{BASE}/orders/{order['id']}/send", headers=auth_headers)

    refused = await client.delete(f"{BASE}/suppliers/{supplier['id']}", headers=auth_headers)
    assert refused.status_code == 422
    assert refused.json()["code"] == "purchasing.supplier.has_open_orders"

    await client.post(f"{BASE}/orders/{order['id']}/cancel", headers=auth_headers)
    assert (
        await client.delete(f"{BASE}/suppliers/{supplier['id']}", headers=auth_headers)
    ).status_code == 204


async def test_one_clinic_never_sees_another_clinics_orders(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic, db_session: AsyncSession
) -> None:
    from uuid import uuid4

    from app.modules.purchasing.models import PurchaseOrder, Supplier

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
    their_supplier = Supplier(clinic_id=other.id, name="Dental Supplies SL")
    db_session.add(their_supplier)
    await db_session.flush()
    db_session.add(
        PurchaseOrder(
            clinic_id=other.id,
            supplier_id=their_supplier.id,
            number="P-2026-0001",
            status="sent",
            order_date=date.today(),
            sent_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    # The same supplier name and the same order number in both clinics.
    await _supplier(client, auth_headers)
    item = await _item(client, auth_headers)
    mine = await _order(
        client,
        auth_headers,
        (await client.get(f"{BASE}/suppliers", headers=auth_headers)).json()["data"][0],
        [{"item_id": item["id"], "quantity_ordered": "10", "unit_cost": "1"}],
    )
    assert mine["number"] == f"P-{date.today().year}-0001"

    listed = await client.get(f"{BASE}/orders", headers=auth_headers)
    assert len(listed.json()["data"]) == 1

    assert (await StockService.item_totals(db_session, other.id)) == {}


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", f"{BASE}/suppliers"), ("get", f"{BASE}/orders")],
)
async def test_every_endpoint_needs_a_session(client: AsyncClient, method: str, path: str) -> None:
    assert (await getattr(client, method)(path)).status_code == 401
