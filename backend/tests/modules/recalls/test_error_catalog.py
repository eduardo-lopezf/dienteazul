"""Recall errors have stable codes and request references."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient

from app.modules.recalls.errors import ERROR_CATALOG


@pytest.mark.asyncio
async def test_missing_recall_error_is_traceable(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    response = await client.get(
        f"/api/v1/recalls/{UUID(int=0)}",
        headers=auth_headers,
    )

    definition = ERROR_CATALOG["recalls.recall.not_found"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]
