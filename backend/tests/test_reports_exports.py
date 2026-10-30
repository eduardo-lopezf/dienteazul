"""The Productividad reports as downloadable tables.

The figures themselves are covered by the report services' own tests;
what is asserted here is the part a person meets in Excel — that the
download arrives as a ZIP with the screen's tables in it, that the
separator decides the decimal mark, and that the stored keys are
translated on the way out.
"""

from __future__ import annotations

import io
import zipfile
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.auth.models import Clinic
from app.core.exports import UTF8_BOM, to_csv
from app.modules.reports.exports import period_name

EXPORTS = [
    ("billing", {"resumen.csv", "por-metodo-de-pago.csv", "facturas-vencidas.csv"}),
    ("budgets", {"resumen.csv", "por-estado.csv", "por-tratamiento.csv"}),
    ("scheduling", {"resumen.csv", "por-profesional.csv", "por-dia-de-la-semana.csv"}),
]

PERIOD = {"date_from": "2026-01-01", "date_to": "2026-12-31"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("report", "expected"), EXPORTS)
async def test_export_returns_the_screens_tables(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    report: str,
    expected: set[str],
) -> None:
    response = await client.get(
        f"/api/v1/reports/{report}/export", params=PERIOD, headers=auth_headers
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert expected <= set(archive.namelist())
    # Every file is a CSV Excel-ES can open: BOM first, headers on line 1.
    for name in archive.namelist():
        content = archive.read(name)
        assert content.startswith(UTF8_BOM), name
        assert content.decode("utf-8-sig").splitlines()[0], name


@pytest.mark.asyncio
async def test_an_empty_period_still_exports_its_headers(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """A clinic with no data gets the columns, not an error or a blank file.

    Somebody who exports a quiet month should be able to see *what* was
    quiet rather than wonder whether the download failed.
    """
    response = await client.get(
        "/api/v1/reports/budgets/export",
        params={"date_from": "1999-01-01", "date_to": "1999-01-31"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    por_estado = archive.read("por-estado.csv").decode("utf-8-sig")
    assert por_estado.splitlines()[0] == "estado;presupuestos;importe"


@pytest.mark.asyncio
async def test_the_separator_decides_the_decimal_mark(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """``;`` pairs with comma decimals, ``,`` with dots — Excel-ES's rule."""
    semicolon = await client.get(
        "/api/v1/reports/billing/export",
        params={**PERIOD, "separator": ";"},
        headers=auth_headers,
    )
    comma = await client.get(
        "/api/v1/reports/billing/export",
        params={**PERIOD, "separator": ","},
        headers=auth_headers,
    )

    def resumen(response) -> str:
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        return archive.read("resumen.csv").decode("utf-8-sig").splitlines()[1]

    assert ";" in resumen(semicolon)
    assert "0,00" in resumen(semicolon)
    assert "0.00" in resumen(comma)


@pytest.mark.asyncio
async def test_an_unknown_separator_is_refused(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """Only the two Excel knows. A tab would silently produce one column."""
    response = await client.get(
        "/api/v1/reports/billing/export",
        params={**PERIOD, "separator": "\t"},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_export_needs_the_same_permission_as_reading(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """No clinic membership, no report — and so no file of it either."""
    response = await client.get(
        "/api/v1/reports/billing/export", params=PERIOD, headers=auth_headers
    )
    assert response.status_code == 403


def test_the_period_is_in_the_filename() -> None:
    """A folder of downloads has to say which month each one is."""
    from datetime import date

    assert (
        period_name("facturacion", date(2026, 9, 1), date(2026, 9, 30))
        == "facturacion_2026-09-01_2026-09-30.zip"
    )


def test_a_missing_column_is_empty_rather_than_a_crash() -> None:
    """Rows come from several services; one that omits a key must not 500."""
    csv_bytes = to_csv([{"a": Decimal("1.5")}], ["a", "b"], ";")
    assert csv_bytes.decode("utf-8-sig").splitlines()[1] == "1,50;"
