"""What a member files when something did not work: written by the clinic
at ``POST /api/v1/error-reports``, read by the operator through
``/api/v1/ops/error-reports``.

The report is prose, so the thing worth pinning down is the boundary: a
clinic can file one and read none, the operator reads them all, and the
query string of the route the member was on never arrives.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config import settings
from app.core.auth.models import Clinic

from .test_ops_endpoint import SECRET, _token


@pytest.fixture
def ops_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CONTROL_PLANE_SECRET", SECRET)


async def _file(client: AsyncClient, headers: dict[str, str], **report) -> tuple[int, dict]:
    body = {
        "description": "Al guardar el presupuesto se queda cargando",
        "path": "/budgets/8f2/edit",
    } | report
    response = await client.post("/api/v1/error-reports", json=body, headers=headers)
    return response.status_code, response.json() if response.content else {}


async def _listed(client: AsyncClient, **params) -> list[dict]:
    response = await client.get("/api/v1/ops/error-reports", headers=_token(), params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_a_member_files_a_report_and_the_operator_reads_it(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    code, _ = await _file(client, auth_headers, app_version="2.0.0")
    assert code == 201

    reports = await _listed(client)
    assert len(reports) == 1
    assert reports[0] == {
        "id": reports[0]["id"],
        "description": "Al guardar el presupuesto se queda cargando",
        "path": "/budgets/8f2/edit",
        "app_version": "2.0.0",
        "state": "new",
        "created_at": reports[0]["created_at"],
        "clinic_id": str(test_clinic.id),
        "clinic_name": "Test Clinic",
        "user_email": "test@example.com",
    }


async def test_the_query_string_of_the_route_is_not_kept(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    # Whatever a query string carries is usually somebody's identifier.
    await _file(client, auth_headers, path="/patients?search=Garcia&id=abc")
    assert (await _listed(client))[0]["path"] == "/patients"


async def test_a_clinic_cannot_read_the_reports(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    await _file(client, auth_headers)
    # There is no clinic-facing route to read them, and the operator's
    # does not open to a staff token.
    assert (await client.get("/api/v1/error-reports", headers=auth_headers)).status_code == 405
    assert (await client.get("/api/v1/ops/error-reports", headers=auth_headers)).status_code == 401


async def test_signing_in_is_required_to_file_one(client: AsyncClient, ops_enabled: None) -> None:
    code, _ = await _file(client, {})
    assert code == 401


@pytest.mark.parametrize(
    "report",
    [
        {"description": "   "},
        {"description": ""},
        {"description": "x" * 2001},
        {"path": ""},
        {"app_version": "x" * 41},
    ],
    ids=["blank", "empty", "too long", "no route", "version too long"],
)
async def test_a_report_with_nothing_in_it_is_refused(
    client: AsyncClient,
    ops_enabled: None,
    test_clinic: Clinic,
    auth_headers: dict[str, str],
    report: dict,
) -> None:
    code, _ = await _file(client, auth_headers, **report)
    assert code == 422


async def test_the_operator_marks_a_report_read_and_archives_it(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    await _file(client, auth_headers)
    report = (await _listed(client))[0]
    url = f"/api/v1/ops/error-reports/{report['id']}"

    read = await client.patch(url, json={"state": "read"}, headers=_token())
    assert read.status_code == 200, read.text
    assert read.json()["data"]["state"] == "read"
    # What the member wrote is theirs: marking it read changes nothing else.
    assert read.json()["data"]["description"] == report["description"]

    assert (
        await client.patch(url, json={"state": "archived"}, headers=_token())
    ).status_code == 200
    assert [r["state"] for r in await _listed(client)] == ["archived"]
    assert await _listed(client, state="new") == []
    assert len(await _listed(client, state="archived")) == 1


async def test_a_state_that_does_not_exist_is_refused(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    await _file(client, auth_headers)
    report = (await _listed(client))[0]
    url = f"/api/v1/ops/error-reports/{report['id']}"
    assert (await client.patch(url, json={"state": "solved"}, headers=_token())).status_code == 422
    assert (
        await client.get("/api/v1/ops/error-reports", headers=_token(), params={"state": "solved"})
    ).status_code == 422


async def test_the_operator_empties_the_reports(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    """As ``DELETE /ops/errors`` empties the server's own failures."""
    await _file(client, auth_headers, description="Uno")
    await _file(client, auth_headers, description="Dos")
    assert len(await _listed(client)) == 2

    cleared = await client.delete("/api/v1/ops/error-reports", headers=_token())
    assert cleared.status_code == 204
    assert await _listed(client) == []


async def test_only_the_archived_ones_can_be_cleared(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    """The usual tidy-up: forget what has been dealt with, keep the rest."""
    await _file(client, auth_headers, description="Pendiente")
    await _file(client, auth_headers, description="Ya resuelto")
    done = next(r for r in await _listed(client) if r["description"] == "Ya resuelto")
    await client.patch(
        f"/api/v1/ops/error-reports/{done['id']}", json={"state": "archived"}, headers=_token()
    )

    cleared = await client.delete(
        "/api/v1/ops/error-reports", headers=_token(), params={"state": "archived"}
    )
    assert cleared.status_code == 204
    assert [r["description"] for r in await _listed(client)] == ["Pendiente"]

    bad = await client.delete(
        "/api/v1/ops/error-reports", headers=_token(), params={"state": "solved"}
    )
    assert bad.status_code == 422


async def test_one_report_is_forgotten_on_its_own(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    await _file(client, auth_headers, description="Uno")
    await _file(client, auth_headers, description="Dos")
    one = (await _listed(client))[0]

    url = f"/api/v1/ops/error-reports/{one['id']}"
    assert (await client.delete(url, headers=_token())).status_code == 204
    assert [r["id"] for r in await _listed(client)] != [one["id"]]
    assert len(await _listed(client)) == 1
    assert (await client.delete(url, headers=_token())).status_code == 404


async def test_a_clinic_cannot_empty_the_reports(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    await _file(client, auth_headers)
    assert (
        await client.delete("/api/v1/ops/error-reports", headers=auth_headers)
    ).status_code == 401
    assert len(await _listed(client)) == 1
