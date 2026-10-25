"""Billing API errors expose stable codes and a traceable request reference."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.modules.billing.errors import ERROR_CATALOG


@pytest.mark.asyncio
async def test_missing_invoice_error_is_traceable(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    response = await client.get(
        "/api/v1/billing/invoices/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )

    definition = ERROR_CATALOG["billing.invoice.not_found"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_invalid_compliance_filter_uses_billing_error_code(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    response = await client.get(
        "/api/v1/billing/invoices?compliance_severity=unexpected",
        headers=auth_headers,
    )

    definition = ERROR_CATALOG["billing.invoice.compliance_severity_invalid"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["reference"] == response.headers["x-request-id"]
