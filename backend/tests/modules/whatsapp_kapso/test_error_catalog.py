"""WhatsApp Kapso errors expose stable codes and request references."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.modules.whatsapp_kapso.errors import ERROR_CATALOG

WEBHOOK = "/api/v1/whatsapp_kapso/webhook"


@pytest.mark.asyncio
async def test_invalid_webhook_json_error_is_traceable(client: AsyncClient) -> None:
    response = await client.post(
        WEBHOOK, content=b"{", headers={"Content-Type": "application/json"}
    )

    definition = ERROR_CATALOG["whatsapp_kapso.webhook.invalid_json"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_invalid_webhook_signature_error_is_traceable(
    client: AsyncClient, db_session, test_clinic
) -> None:
    from app.core.email.encryption import encrypt_password
    from app.modules.whatsapp_kapso.models import WhatsappKapsoSettings

    db_session.add(
        WhatsappKapsoSettings(
            clinic_id=test_clinic.id,
            api_key_encrypted=encrypt_password("key"),
            phone_number_id="PNID-ERROR-TRACE",
            webhook_secret_encrypted=encrypt_password("secret"),
            is_active=True,
        )
    )
    await db_session.commit()

    response = await client.post(
        WEBHOOK,
        json={"phone_number_id": "PNID-ERROR-TRACE", "message": {}},
        headers={"X-Webhook-Signature": "invalid"},
    )

    definition = ERROR_CATALOG["whatsapp_kapso.webhook.invalid_signature"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["message"] == definition.message
    assert body["reference"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_non_object_webhook_json_is_rejected_as_traceable_payload_error(
    client: AsyncClient,
) -> None:
    response = await client.post(
        WEBHOOK, content=b"[]", headers={"Content-Type": "application/json"}
    )

    definition = ERROR_CATALOG["whatsapp_kapso.webhook.invalid_payload"]
    body = response.json()
    assert response.status_code == definition.status_code
    assert body["code"] == definition.code
    assert body["reference"] == response.headers["x-request-id"]
