"""Server errors are kept for the operator (``app.core.server_errors``) and
read by the control panel at ``/api/v1/ops/errors``: where each failed,
never the values it was working on."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.core.auth.dependencies import ClinicContext, get_clinic_context
from app.core.auth.models import Clinic
from app.core.server_errors import scrub
from app.main import app

from .test_ops_endpoint import SECRET, _token

BROKEN = "/api/v1/__test__/broken/{item_id}"


@pytest.fixture
def ops_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CONTROL_PLANE_SECRET", SECRET)


@pytest.fixture
async def broken_route(client: AsyncClient) -> AsyncIterator[AsyncClient]:
    """A route that fails as a bug would, and a client that receives the
    500 the way a browser does instead of the exception."""

    async def broken(
        item_id: str, ctx: Annotated[ClinicContext, Depends(get_clinic_context)]
    ) -> None:
        raise ValueError(f"no row for 'ana.perez@example.com' with id {item_id} 5512345678")

    app.add_api_route(BROKEN, broken, methods=["GET"])
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as browser:
            yield browser
    finally:
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != BROKEN]


async def test_a_server_error_is_kept_with_its_origin(
    broken_route: AsyncClient,
    client: AsyncClient,
    ops_enabled: None,
    test_clinic: Clinic,
    auth_headers: dict[str, str],
) -> None:
    response = await broken_route.get(
        "/api/v1/__test__/broken/42", headers=auth_headers | {"X-Request-Id": "rastreo-123"}
    )
    assert response.status_code == 500

    listed = await client.get("/api/v1/ops/errors", headers=_token())
    assert listed.status_code == 200, listed.text
    [error] = listed.json()["data"]
    # The route's template, not the path with its identifier.
    assert (error["method"], error["path"]) == ("GET", BROKEN)
    assert error["error_type"] == "builtins.ValueError"
    assert error["request_id"] == "rastreo-123"
    assert error["clinic_id"] == str(test_clinic.id)
    assert error["user_id"]
    assert "in broken" in error["frames"]
    # What it was working on stays out.
    assert "ana.perez" not in error["message"]
    assert "5512345678" not in error["message"]


async def test_only_the_control_plane_reads_or_clears_them(
    client: AsyncClient, ops_enabled: None, auth_headers: dict[str, str]
) -> None:
    assert (await client.get("/api/v1/ops/errors", headers=auth_headers)).status_code == 401
    assert (await client.delete("/api/v1/ops/errors", headers=_token())).status_code == 204
    assert (await client.get("/api/v1/ops/errors", headers=_token())).json()["data"] == []


@pytest.mark.parametrize(
    "message,kept,gone",
    [
        (
            'duplicate key value violates unique constraint "users_email_key"\n'
            "DETAIL:  Key (email)=(ana@example.com) already exists.\n"
            "[SQL: INSERT INTO users (email) VALUES ($1)]\n"
            "[parameters: ('ana@example.com',)]\n"
            "(Background on this error at: https://sqlalche.me/e/20/gkpj)",
            ["users_email_key", "Key (email)=(…) already exists"],
            ["ana@example.com", "sqlalche.me"],
        ),
        ("could not find 'Juana López Hernández'", ["could not find"], ["Juana"]),
        ("phone 5512345678 rejected", ["phone", "rejected"], ["5512345678"]),
    ],
    ids=["database constraint", "quoted value", "long number"],
)
def test_a_message_loses_the_values_it_quoted(
    message: str, kept: list[str], gone: list[str]
) -> None:
    cleaned = scrub(message)
    for part in kept:
        assert part in cleaned
    for part in gone:
        assert part not in cleaned
