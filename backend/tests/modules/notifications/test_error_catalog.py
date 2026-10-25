"""Notification failures use stable catalog codes and request references."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.modules.notifications.errors import ERROR_CATALOG


@pytest.mark.asyncio
async def test_missing_template_error_is_traceable(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    response = await client.get(
        "/api/v1/notifications/templates/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )

    definition = ERROR_CATALOG["notifications.template.not_found"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]
