"""Report errors have stable codes and request references."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.plugins.registry import module_registry
from app.modules.reports.errors import ERROR_CATALOG


@pytest.mark.asyncio
async def test_disabled_report_integration_error_is_traceable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    was_active = module_registry.is_installed("billing")
    module_registry.deactivate("billing")
    try:
        response = await client.get(
            "/api/v1/reports/billing/summary",
            params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
            headers=auth_headers,
        )
    finally:
        if was_active:
            module_registry.activate("billing")

    definition = ERROR_CATALOG["reports.integration.unavailable"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_invalid_lifecycle_date_range_is_traceable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/reports/scheduling/waiting-times",
        params={"date_from": "2026-02-02", "date_to": "2026-02-01"},
        headers=auth_headers,
    )

    definition = ERROR_CATALOG["reports.date_range.invalid"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["reference"] == response.headers["x-request-id"]
