"""Liquidation errors have stable codes and request references."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient

from app.modules.liquidations.errors import ERROR_CATALOG


@pytest.mark.asyncio
async def test_missing_liquidation_error_is_traceable(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    response = await client.get(
        f"/api/v1/liquidations/{UUID(int=0)}",
        headers=auth_headers,
    )

    definition = ERROR_CATALOG["liquidations.settlement.not_found"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_invalid_settlement_period_is_traceable(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    response = await client.get(
        "/api/v1/liquidations/preview",
        params={
            "professional_id": str(UUID(int=0)),
            "date_from": "2026-02-02",
            "date_to": "2026-02-01",
        },
        headers=auth_headers,
    )

    definition = ERROR_CATALOG["liquidations.period.invalid"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["reference"] == response.headers["x-request-id"]
