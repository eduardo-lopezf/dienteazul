"""Record errors have stable codes and request references."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient

from app.modules.record.errors import ERROR_CATALOG


@pytest.mark.asyncio
async def test_missing_patient_record_error_is_traceable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get(
        f"/api/v1/record/patients/{UUID(int=0)}",
        headers=auth_headers,
    )

    definition = ERROR_CATALOG["record.patient.not_found"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_invalid_disclosure_error_is_traceable(
    client: AsyncClient, auth_headers: dict[str, str], test_patient
) -> None:
    response = await client.post(
        f"/api/v1/record/patients/{test_patient.id}/disclosures",
        headers=auth_headers,
        json={
            "purpose": "continuity_of_care",
            "recipient_name": "Referral",
            "evidence": "",
            "scope": [],
        },
    )

    definition = ERROR_CATALOG["record.disclosure.invalid"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["reference"] == response.headers["x-request-id"]
