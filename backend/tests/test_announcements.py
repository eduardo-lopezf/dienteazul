"""The operator's notices to clinics: written through ``/api/v1/ops``,
read by each clinic's members at ``GET /api/v1/announcements`` — only the
ones in force, and only those meant for that clinic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.config import settings
from app.core.auth.models import Clinic

from .test_ops_endpoint import SECRET, _token


@pytest.fixture
def ops_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CONTROL_PLANE_SECRET", SECRET)


async def _publish(client: AsyncClient, **notice) -> dict:
    body = {"kind": "maintenance", "message": "Mantenimiento el domingo"} | notice
    response = await client.post("/api/v1/ops/announcements", json=body, headers=_token())
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _seen(client: AsyncClient, headers: dict[str, str]) -> list[str]:
    response = await client.get("/api/v1/announcements", headers=headers)
    assert response.status_code == 200, response.text
    return [a["message"] for a in response.json()["data"]]


def _at(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


async def test_only_the_control_plane_publishes(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    body = {"kind": "feature", "message": "Nuevo"}
    response = await client.post("/api/v1/ops/announcements", json=body, headers=auth_headers)
    assert response.status_code == 401


async def test_a_clinic_sees_the_notices_in_force_for_it(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    await _publish(client, message="Para todas")
    await _publish(
        client, kind="feature", message="Solo para esta", clinic_ids=[str(test_clinic.id)]
    )
    await _publish(client, message="Para otra", clinic_ids=[str(uuid4())])
    scheduled = await _publish(client, message="Todavía no", starts_at=_at(hours=1))
    await _publish(client, message="Ya pasó", starts_at=_at(hours=-2), ends_at=_at(hours=-1))

    assert set(await _seen(client, auth_headers)) == {"Para todas", "Solo para esta"}

    listed = await client.get("/api/v1/ops/announcements", headers=_token())
    statuses = {a["message"]: a["status"] for a in listed.json()["data"]}
    assert statuses == {
        "Para todas": "active",
        "Solo para esta": "active",
        "Para otra": "active",
        "Todavía no": "scheduled",
        "Ya pasó": "ended",
    }
    assert scheduled["status"] == "scheduled"


async def test_a_notice_is_changed_and_taken_down(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    notice = await _publish(client)
    url = f"/api/v1/ops/announcements/{notice['id']}"

    changed = await client.put(
        url, json={"kind": "feature", "message": "  Ahora hay recordatorios  "}, headers=_token()
    )
    assert changed.status_code == 200, changed.text
    assert await _seen(client, auth_headers) == ["Ahora hay recordatorios"]

    assert (await client.delete(url, headers=_token())).status_code == 204
    assert await _seen(client, auth_headers) == []
    assert (await client.delete(url, headers=_token())).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "maintenance", "message": "   "},
        {"kind": "outage", "message": "Caída"},
        {"kind": "feature", "message": "x" * 281},
    ],
    ids=["empty", "unknown kind", "too long"],
)
async def test_a_notice_that_cannot_be_shown_is_refused(
    client: AsyncClient, ops_enabled: None, body: dict
) -> None:
    response = await client.post("/api/v1/ops/announcements", json=body, headers=_token())
    assert response.status_code == 422


async def test_a_notice_cannot_end_before_it_starts(client: AsyncClient, ops_enabled: None) -> None:
    body = {
        "kind": "feature",
        "message": "Al revés",
        "starts_at": _at(hours=2),
        "ends_at": _at(hours=1),
    }
    response = await client.post("/api/v1/ops/announcements", json=body, headers=_token())
    assert response.status_code == 422
