"""Accounting export errors have stable codes and request references."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.modules.accounting_export.errors import ERROR_CATALOG


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/preview", "/run"])
async def test_reversed_export_period_error_is_traceable(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic, path: str
) -> None:
    response = await client.get(
        f"/api/v1/accounting_export{path}",
        params={"date_from": "2026-06-01", "date_to": "2026-05-01"},
        headers=auth_headers,
    )

    definition = ERROR_CATALOG["accounting_export.period.invalid"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]
