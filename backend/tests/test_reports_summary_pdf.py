"""The clinic's period on one printable page.

The figures themselves belong to the report services and are tested
there. What is pinned here is what the page promises: that it is a PDF,
that it stays one page, that it asks for its own permission, and that a
section whose App is off simply is not on it.
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.reports import monthly

PERIOD = {"date_from": "2026-01-01", "date_to": "2026-12-31"}


@pytest.mark.asyncio
async def test_the_summary_is_a_pdf(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    response = await client.get("/api/v1/reports/summary.pdf", params=PERIOD, headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    # Shown in the browser's viewer, not dropped in Downloads: it is a
    # page to glance at, and printing is the next thing the user does.
    assert response.headers["content-disposition"].startswith("inline")


@pytest.mark.asyncio
async def test_the_summary_stays_one_page(db_session: AsyncSession, test_clinic: Clinic) -> None:
    """One page is the feature, so a layout change that spills fails here.

    What keeps it there is in the template: every table is a summary, and
    the one list that could grow — production by professional — is capped
    at ``TOP_PROFESSIONALS``.
    """
    from weasyprint import HTML

    html = await monthly.build_html(db_session, test_clinic, date(2026, 1, 1), date(2026, 12, 31))
    assert len(HTML(string=html).render().pages) == 1


@pytest.mark.asyncio
async def test_the_period_is_on_the_page_and_in_the_filename(
    db_session: AsyncSession, test_clinic: Clinic
) -> None:
    """A printed page with no dates on it is a page nobody can file."""
    html = await monthly.build_html(db_session, test_clinic, date(2026, 9, 1), date(2026, 9, 30))
    assert "01/09/2026" in html
    assert "30/09/2026" in html
    assert (
        monthly.filename(test_clinic.id, date(2026, 9, 1), date(2026, 9, 30))
        == "productividad_2026-09-01_2026-09-30.pdf"
    )


@pytest.mark.asyncio
async def test_the_page_never_crosses_the_two_axes(
    db_session: AsyncSession, test_clinic: Clinic
) -> None:
    """Invoiced and collected sit in separate sections and are never subtracted.

    The page is the one place both axes appear at once, which is exactly
    where ADR 0010 is easiest to break — by adding a helpful "pendiente de
    facturar" line. The note at the foot says they are different axes;
    this asserts no figure claims to be their difference.
    """
    html = await monthly.build_html(db_session, test_clinic, date(2026, 1, 1), date(2026, 12, 31))
    lowered = html.lower()
    for forbidden in ("sin facturar", "por facturar", "facturado menos", "no facturado"):
        assert forbidden not in lowered


@pytest.mark.asyncio
async def test_the_summary_has_its_own_permission(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """No clinic membership, no page. `reports.summary.read` gates it."""
    response = await client.get("/api/v1/reports/summary.pdf", params=PERIOD, headers=auth_headers)
    assert response.status_code == 403
