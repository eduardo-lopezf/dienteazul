"""The collections report as a downloadable bundle.

What is asserted here is the part a person meets in Excel — the ZIP
arrives with the screen's tables, the separator decides the decimal mark,
and the stored keys are translated — plus the one rule this module
cannot break: the file carries the collection axis and nothing from the
invoice axis (ADR 0010).
"""

from __future__ import annotations

import io
import zipfile

import pytest
from httpx import AsyncClient

from app.core.auth.models import Clinic

PERIOD = {"date_from": "2026-01-01", "date_to": "2026-12-31"}

EXPECTED_FILES = {
    "resumen.csv",
    "evolucion.csv",
    "por-metodo.csv",
    "por-profesional.csv",
    "antiguedad-hoy.csv",
    "devoluciones-por-motivo.csv",
}


async def _export(client: AsyncClient, headers: dict[str, str], **params) -> zipfile.ZipFile:
    response = await client.get(
        "/api/v1/payments/reports/export", params={**PERIOD, **params}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(response.content))


@pytest.mark.asyncio
async def test_export_carries_every_card_of_the_screen(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    archive = await _export(client, auth_headers)
    assert set(archive.namelist()) == EXPECTED_FILES


@pytest.mark.asyncio
async def test_export_is_the_collection_axis_only(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """No invoiced column, and nothing derived from invoiced minus collected.

    A clinic legitimately leaves work off the invoice; a file that put the
    two axes side by side would document that, which is the thing ADR 0010
    forbids. The guard is on the header row because that is what a new
    column has to pass through.
    """
    archive = await _export(client, auth_headers)
    forbidden = ("facturad", "invoiced", "por_facturar", "sin_facturar")

    for name in archive.namelist():
        header = archive.read(name).decode("utf-8-sig").splitlines()[0].lower()
        for word in forbidden:
            assert word not in header, f"{name} exposes the invoice axis: {header}"


@pytest.mark.asyncio
async def test_the_separator_decides_the_decimal_mark(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    semicolon = await _export(client, auth_headers, separator=";")
    comma = await _export(client, auth_headers, separator=",")

    def resumen(archive: zipfile.ZipFile) -> str:
        return archive.read("resumen.csv").decode("utf-8-sig").splitlines()[1]

    assert "0,00" in resumen(semicolon)
    assert "0.00" in resumen(comma)


@pytest.mark.asyncio
async def test_the_granularity_reaches_the_trend_file(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """The screen's day/week/month toggle has to travel with the download."""
    archive = await _export(client, auth_headers, granularity="day")
    header = archive.read("evolucion.csv").decode("utf-8-sig").splitlines()[0]
    assert header == "inicio_del_tramo;cobrado;devuelto;neto"


@pytest.mark.asyncio
async def test_an_unknown_separator_is_refused(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    response = await client.get(
        "/api/v1/payments/reports/export",
        params={**PERIOD, "separator": "|"},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_export_needs_the_reports_permission(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """No clinic membership, no report — and so no file of it either."""
    response = await client.get(
        "/api/v1/payments/reports/export", params=PERIOD, headers=auth_headers
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_the_export_route_is_not_eaten_by_the_payment_id_route(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """Every literal path here has to be declared before ``/{payment_id}``.

    ``/reports/refunds`` once answered 422 "reports is not a valid UUID";
    this pins the same trap for the export.
    """
    response = await client.get(
        "/api/v1/payments/reports/export", params=PERIOD, headers=auth_headers
    )
    assert response.status_code != 422
