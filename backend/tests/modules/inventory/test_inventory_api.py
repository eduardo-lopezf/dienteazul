"""The inventory API: the surface, and the three refusals that matter.

The service tests own the arithmetic (``test_stock_ledger.py``). What is
pinned here is what reaches the outside: an article round-trips, stock
reads back with its totals, an adjustment is not something
``stock.write`` can post, and a refusal carries a stable code.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.modules.inventory.errors import ERROR_CATALOG

BASE = "/api/v1/inventory"


def _item(**overrides) -> dict:
    body = {
        "code": "COM-A2",
        "name": "Composite A2",
        "base_unit": "jeringa",
        "category": "restorative",
        "reorder_point": "3",
        "reorder_quantity": "10",
    }
    body.update(overrides)
    return body


async def _create_item(client: AsyncClient, headers: dict, **overrides) -> dict:
    response = await client.post(f"{BASE}/items", json=_item(**overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_an_article_round_trips(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    created = await _create_item(client, auth_headers)
    assert created["tracks_lots"] is False

    listed = await client.get(f"{BASE}/items", headers=auth_headers)
    assert listed.status_code == 200
    assert [item["code"] for item in listed.json()["data"]] == ["COM-A2"]

    updated = await client.put(
        f"{BASE}/items/{created['id']}",
        json={"reorder_point": "5"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    # Master data keeps the scale it was sent with; the ledger is the
    # place that normalises (``QUANTITY_STEP``).
    assert Decimal(updated.json()["data"]["reorder_point"]) == Decimal("5")

    archived = await client.delete(f"{BASE}/items/{created['id']}", headers=auth_headers)
    assert archived.status_code == 204
    after = await client.get(f"{BASE}/items", headers=auth_headers)
    assert after.json()["data"] == []


async def test_a_receipt_shows_up_in_stock(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    """No location is sent: the first receipt creates the default one.

    Refusing it instead would make the feature read as broken on the
    first thing anybody tries.
    """
    item = await _create_item(client, auth_headers)

    posted = await client.post(
        f"{BASE}/movements",
        json={"item_id": item["id"], "quantity_base": "12", "reason": "purchase_receipt"},
        headers=auth_headers,
    )
    assert posted.status_code == 201, posted.text
    assert posted.json()["data"]["quantity_base"] == "12.000"
    assert posted.json()["data"]["location_name"] == "Almacén"

    stock = await client.get(f"{BASE}/stock", headers=auth_headers)
    line = stock.json()["data"][0]
    assert line["quantity"] == "12.000"
    assert line["item_total"] == "12.000"
    assert line["is_low"] is False

    ledger = await client.get(f"{BASE}/movements", headers=auth_headers)
    assert ledger.json()["total"] == 1
    assert ledger.json()["data"][0]["reason"] == "purchase_receipt"


async def test_the_ledger_says_who_posted_each_line(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    """A ledger whose "who" column is a UUID is a ledger nobody reads.

    The name comes from core's ``users``, which this module may join —
    it is not another module's table.
    """
    item = await _create_item(client, auth_headers)
    await client.post(
        f"{BASE}/movements",
        json={"item_id": item["id"], "quantity_base": "12", "reason": "purchase_receipt"},
        headers=auth_headers,
    )

    ledger = await client.get(f"{BASE}/movements", headers=auth_headers)
    line = ledger.json()["data"][0]
    assert line["performed_by_user"]["first_name"] == "Test"
    assert line["performed_by_user"]["last_name"] == "User"
    assert line["performed_by_user"]["id"] == line["performed_by"]


async def test_the_ledger_filters_by_article_and_reason(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    gloves = await _create_item(client, auth_headers)
    burs = await _create_item(client, auth_headers, code="FRE-DIA", name="Fresas")
    for item_id in (gloves["id"], burs["id"]):
        await client.post(
            f"{BASE}/movements",
            json={"item_id": item_id, "quantity_base": "10", "reason": "purchase_receipt"},
            headers=auth_headers,
        )
    await client.post(
        f"{BASE}/movements",
        json={"item_id": gloves["id"], "quantity_base": "2", "reason": "consumption"},
        headers=auth_headers,
    )

    by_item = await client.get(f"{BASE}/movements?item_id={gloves['id']}", headers=auth_headers)
    assert by_item.json()["total"] == 2

    by_reason = await client.get(f"{BASE}/movements?reason=consumption", headers=auth_headers)
    assert by_reason.json()["total"] == 1
    assert by_reason.json()["data"][0]["quantity_base"] == "-2.000"


async def test_an_adjustment_is_not_posted_as_a_movement(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    """``/movements`` refuses it: an adjustment says what was counted.

    Routing it through ``/stock/count`` is what keeps the reason bound to
    a count rather than being a free hand on the number.
    """
    item = await _create_item(client, auth_headers)
    response = await client.post(
        f"{BASE}/movements",
        json={"item_id": item["id"], "quantity_base": "-1", "reason": "adjustment"},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "inventory.request.invalid"


async def test_a_count_closes_through_its_own_endpoint(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    item = await _create_item(client, auth_headers)
    await client.post(
        f"{BASE}/movements",
        json={"item_id": item["id"], "quantity_base": "12", "reason": "purchase_receipt"},
        headers=auth_headers,
    )
    locations = await client.get(f"{BASE}/locations", headers=auth_headers)
    location_id = locations.json()["data"][0]["id"]

    counted = await client.post(
        f"{BASE}/stock/count",
        json={
            "lines": [{"item_id": item["id"], "location_id": location_id, "counted_quantity": "9"}],
            "note": "Recuento de noviembre",
        },
        headers=auth_headers,
    )
    assert counted.status_code == 201, counted.text
    assert counted.json()["data"]["adjustments_posted"] == 1

    stock = await client.get(f"{BASE}/stock", headers=auth_headers)
    assert stock.json()["data"][0]["quantity"] == "9.000"
    assert stock.json()["data"][0]["is_low"] is False

    # And the snapshot still agrees with the ledger afterwards.
    reconciled = await client.post(f"{BASE}/stock/reconcile", headers=auth_headers)
    assert reconciled.json()["data"]["corrected"] == 0


async def test_taking_more_than_there_is_refuses_with_a_stable_code(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    item = await _create_item(client, auth_headers)
    response = await client.post(
        f"{BASE}/movements",
        json={"item_id": item["id"], "quantity_base": "1", "reason": "consumption"},
        headers=auth_headers,
    )

    definition = ERROR_CATALOG["inventory.stock.insufficient"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["reference"] == response.headers["x-request-id"]


async def test_a_missing_article_is_a_404_with_a_reference(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    response = await client.get(
        f"{BASE}/items/00000000-0000-0000-0000-000000000000", headers=auth_headers
    )
    definition = ERROR_CATALOG["inventory.item.not_found"]
    assert response.status_code == definition.status_code
    assert response.json()["code"] == definition.code
    assert response.json()["reference"] == response.headers["x-request-id"]


async def test_a_lot_tracked_article_takes_its_lot_through_the_api(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    item = await _create_item(
        client, auth_headers, code="ANE-ART", name="Articaína", tracks_lots=True
    )
    lot = await client.post(
        f"{BASE}/items/{item['id']}/lots",
        json={"lot_code": "L-2027-03", "expires_on": "2027-03-31"},
        headers=auth_headers,
    )
    assert lot.status_code == 201, lot.text

    without_lot = await client.post(
        f"{BASE}/movements",
        json={"item_id": item["id"], "quantity_base": "50", "reason": "purchase_receipt"},
        headers=auth_headers,
    )
    assert without_lot.status_code == 422
    assert without_lot.json()["code"] == "inventory.lot.required"

    with_lot = await client.post(
        f"{BASE}/movements",
        json={
            "item_id": item["id"],
            "lot_id": lot.json()["data"]["id"],
            "quantity_base": "50",
            "reason": "purchase_receipt",
        },
        headers=auth_headers,
    )
    assert with_lot.status_code == 201, with_lot.text
    assert with_lot.json()["data"]["lot_code"] == "L-2027-03"


async def test_the_same_article_code_cannot_be_used_twice(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    await _create_item(client, auth_headers)
    again = await client.post(f"{BASE}/items", json=_item(), headers=auth_headers)
    assert again.status_code == 409
    assert again.json()["code"] == "inventory.item.code_taken"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", f"{BASE}/stock"),
        ("get", f"{BASE}/items"),
        ("get", f"{BASE}/movements"),
        ("post", f"{BASE}/stock/reconcile"),
    ],
)
async def test_every_endpoint_needs_a_session(client: AsyncClient, method: str, path: str) -> None:
    response = await getattr(client, method)(path)
    assert response.status_code == 401
