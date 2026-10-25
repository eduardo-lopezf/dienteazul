"""Schedule failures use stable catalog codes and request references."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.modules.schedules.errors import ERROR_CATALOG


@pytest.mark.asyncio
async def test_missing_clinic_override_error_is_traceable(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    response = await client.put(
        "/api/v1/schedules/clinic-overrides/00000000-0000-0000-0000-000000000000",
        json={
            "start_date": "2026-10-23",
            "end_date": "2026-10-23",
            "kind": "closed",
            "reason": "Test",
            "shifts": [],
        },
        headers=auth_headers,
    )

    definition = ERROR_CATALOG["schedules.override.not_found"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]
