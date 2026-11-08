"""A route that waits on someone else's server is not slow by accident.

``SLOW_REQUEST_SECONDS`` is what a screen waits for; registering a CSD
with the PAC honestly takes longer, and filing it as slow buries the
requests that are slow by mistake (ADR 0060's companion middleware).
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.server_errors import slow_budget, slow_threshold
from app.main import slow_request_middleware
from app.modules.sat_cfdi.pac import TIMEOUT as PAC_TIMEOUT
from app.modules.sat_cfdi.router import PAC_WAIT, register_certificate, upload_certificate


class FakeRoute:
    """What ``request.scope["route"]`` offers of a route: its endpoint."""

    def __init__(self, endpoint) -> None:
        self.endpoint = endpoint


def test_a_route_without_a_budget_keeps_the_deployments() -> None:
    async def plain() -> None: ...

    assert slow_threshold(FakeRoute(plain), 5.0) == 5.0
    assert slow_threshold(None, 5.0) == 5.0


def test_a_route_can_declare_its_own_budget() -> None:
    @slow_budget(42.0)
    async def waits() -> None: ...

    assert slow_threshold(FakeRoute(waits), 5.0) == 42.0


def test_the_csd_routes_wait_for_facturama() -> None:
    """Both register the CSD with the PAC, so both outlast the five seconds."""
    assert PAC_WAIT > PAC_TIMEOUT
    for endpoint in (upload_certificate, register_certificate):
        assert slow_threshold(FakeRoute(endpoint), 5.0) == PAC_WAIT


@pytest.mark.asyncio
async def test_the_middleware_reads_the_routes_budget(monkeypatch) -> None:
    """Nothing is recorded for a route whose budget it stayed inside."""
    recorded: list[dict] = []
    monkeypatch.setattr("app.main.record_server_event", lambda **kwargs: recorded.append(kwargs))
    monkeypatch.setattr("app.main.settings.SLOW_REQUEST_SECONDS", 0.001)

    app = FastAPI()
    router = APIRouter()

    @router.get("/patient")
    @slow_budget(60.0)
    async def patient() -> dict:
        return {"ok": True}

    @router.get("/hasty")
    async def hasty() -> dict:
        return {"ok": True}

    app.include_router(router)
    app.middleware("http")(slow_request_middleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/patient")).status_code == 200
        assert not recorded
        assert (await client.get("/hasty")).status_code == 200

    assert [event["path"] for event in recorded] == ["/hasty"]
