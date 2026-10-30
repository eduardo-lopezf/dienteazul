"""What the clinic said it wanted, next to what it got.

The arithmetic of attainment is the part a screen draws a traffic light
from, so it is tested as a pure function: the distinction that matters
is "no goal" versus "a goal of zero", which a ratio of ``None`` and a
ratio of ``0`` keep apart.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.auth.models import Clinic
from app.modules.reports import targets


class TestAttainment:
    def test_a_goal_met_is_a_hundred_percent(self) -> None:
        reached = targets.Attainment.of(Decimal("1000"), Decimal("1000"))
        assert reached.ratio == 100.0

    def test_a_goal_half_met(self) -> None:
        assert targets.Attainment.of(Decimal("2000"), Decimal("1000")).ratio == 50.0

    def test_passing_the_goal_is_reported_as_it_is(self) -> None:
        """No cap: a clinic that beat its target wants to see by how much."""
        assert targets.Attainment.of(Decimal("1000"), Decimal("1500")).ratio == 150.0

    def test_no_goal_is_not_a_goal_of_zero(self) -> None:
        """``None`` means nobody set one — a screen must not draw a bar."""
        unset = targets.Attainment.of(None, Decimal("900"))
        assert unset.ratio is None
        assert unset.actual == Decimal("900")

    def test_a_goal_of_zero_does_not_divide(self) -> None:
        """Stored as zero by hand; dividing by it would be the only crash here."""
        assert targets.Attainment.of(Decimal("0"), Decimal("900")).ratio is None


class TestMonthBounds:
    def test_any_day_of_the_month_resolves_to_the_whole_month(self) -> None:
        assert targets.month_bounds(date(2026, 9, 17)) == (date(2026, 9, 1), date(2026, 9, 30))

    def test_february_in_a_leap_year(self) -> None:
        assert targets.month_bounds(date(2028, 2, 10)) == (date(2028, 2, 1), date(2028, 2, 29))

    def test_december_does_not_spill_into_january(self) -> None:
        assert targets.month_bounds(date(2026, 12, 31)) == (date(2026, 12, 1), date(2026, 12, 31))


@pytest.mark.asyncio
async def test_a_month_with_no_goals_still_reports_its_actuals(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """Before anybody sets a target, the figures are still worth seeing."""
    response = await client.get(
        "/api/v1/reports/targets", params={"month": "2026-09-15"}, headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["month"] == "2026-09-01"
    assert data["collected"]["target"] is None
    assert data["collected"]["ratio"] is None


@pytest.mark.asyncio
async def test_goals_are_set_per_month_and_read_back_with_progress(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    put = await client.put(
        "/api/v1/reports/targets",
        params={"month": "2026-09-01"},
        json={"collected_target": "1000.00", "new_patients_target": 4},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text

    get = await client.get(
        "/api/v1/reports/targets", params={"month": "2026-09-30"}, headers=auth_headers
    )
    data = get.json()["data"]
    assert data["collected"]["target"] == "1000.00"
    assert data["new_patients"]["target"] == "4"
    # Untouched goals stay unset rather than defaulting to zero.
    assert data["production"]["target"] is None


@pytest.mark.asyncio
async def test_one_month_does_not_inherit_anothers_goals(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """A goal is a decision about one month, never a standing default."""
    await client.put(
        "/api/v1/reports/targets",
        params={"month": "2026-09-01"},
        json={"collected_target": "1000.00"},
        headers=auth_headers,
    )

    october = await client.get(
        "/api/v1/reports/targets", params={"month": "2026-10-01"}, headers=auth_headers
    )
    assert october.json()["data"]["collected"]["target"] is None


@pytest.mark.asyncio
async def test_a_negative_goal_is_refused(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    response = await client.put(
        "/api/v1/reports/targets",
        params={"month": "2026-09-01"},
        json={"collected_target": "-5.00"},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_setting_a_goal_needs_more_than_reading_one(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """No clinic membership, no goals — read or write."""
    read = await client.get(
        "/api/v1/reports/targets", params={"month": "2026-09-01"}, headers=auth_headers
    )
    write = await client.put(
        "/api/v1/reports/targets",
        params={"month": "2026-09-01"},
        json={"collected_target": "1.00"},
        headers=auth_headers,
    )
    assert read.status_code == 403
    assert write.status_code == 403
