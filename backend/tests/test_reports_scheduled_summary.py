"""The standing order that mails a clinic its own one-page summary.

The date arithmetic is the part that decides whether a clinic gets its
summary once, twice or never, so it is tested as pure functions. The
endpoints are tested for the thing that matters about them: a schedule
starts off, and turning it on is a write.

Nothing here sends mail: the send path is exercised only through the
guards that stop it.
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient

from app.core.auth.models import Clinic
from app.modules.reports import schedule
from app.modules.reports.models import SummarySchedule


class TestWhenASummaryIsDue:
    """A period's figures stop moving the moment it closes — send then."""

    def test_weekly_goes_out_on_monday_for_the_week_just_ended(self) -> None:
        # Monday 5 October 2026.
        period = schedule.period_due("weekly", date(2026, 10, 5))
        assert period == (date(2026, 9, 28), date(2026, 10, 4))

    def test_weekly_sends_nothing_on_any_other_day(self) -> None:
        for day in range(6, 12):  # Tuesday through Sunday
            assert schedule.period_due("weekly", date(2026, 10, day)) is None

    def test_monthly_goes_out_on_the_first_for_the_month_just_ended(self) -> None:
        period = schedule.period_due("monthly", date(2026, 10, 1))
        assert period == (date(2026, 9, 1), date(2026, 9, 30))

    def test_monthly_crosses_the_year_without_help(self) -> None:
        period = schedule.period_due("monthly", date(2026, 1, 1))
        assert period == (date(2025, 12, 1), date(2025, 12, 31))

    def test_monthly_sends_nothing_on_the_second(self) -> None:
        assert schedule.period_due("monthly", date(2026, 10, 2)) is None

    def test_an_unknown_cadence_sends_nothing(self) -> None:
        """A row written by hand, or a cadence retired later, stays quiet."""
        assert schedule.period_due("daily", date(2026, 10, 5)) is None


class TestSendingOnlyOnce:
    """Two workers and a restart must not mean three copies in a mailbox."""

    def test_a_period_already_sent_is_not_sent_again(self) -> None:
        standing_order = SummarySchedule(last_sent_for=date(2026, 9, 30))
        assert schedule.already_sent(standing_order, date(2026, 9, 30)) is True

    def test_a_newer_period_still_goes_out(self) -> None:
        standing_order = SummarySchedule(last_sent_for=date(2026, 9, 30))
        assert schedule.already_sent(standing_order, date(2026, 10, 31)) is False

    def test_a_clinic_that_never_received_one_is_due(self) -> None:
        assert (
            schedule.already_sent(SummarySchedule(last_sent_for=None), date(2026, 9, 30)) is False
        )


class TestTheClinicsOwnCalendar:
    def test_an_unknown_timezone_falls_back_instead_of_raising(self) -> None:
        """A bad value in the clinic row must not stop every other clinic."""
        assert isinstance(schedule.clinic_today("Not/AZone"), date)
        assert isinstance(schedule.clinic_today(None), date)


@pytest.mark.asyncio
async def test_a_clinic_starts_with_the_summary_switched_off(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """Nothing leaves a clinic until somebody asks it to."""
    response = await client.get("/api/v1/reports/summary/schedule", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {
        "is_active": False,
        "cadence": "monthly",
        "recipients": [],
        "last_sent_for": None,
    }


@pytest.mark.asyncio
async def test_the_schedule_can_be_set_and_read_back(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    put = await client.put(
        "/api/v1/reports/summary/schedule",
        json={"is_active": True, "cadence": "weekly", "recipients": ["jefe@clinicademo.com"]},
        headers=auth_headers,
    )
    assert put.status_code == 200

    get = await client.get("/api/v1/reports/summary/schedule", headers=auth_headers)
    assert get.json()["data"]["cadence"] == "weekly"
    assert get.json()["data"]["recipients"] == ["jefe@clinicademo.com"]


@pytest.mark.asyncio
async def test_an_address_that_is_not_one_is_refused(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """A typo here is a summary nobody receives and nobody misses."""
    response = await client.put(
        "/api/v1/reports/summary/schedule",
        json={"is_active": True, "cadence": "weekly", "recipients": ["no-es-un-correo"]},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_recipient_list_is_capped(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    """A standing order on a cron is not a mailing list."""
    response = await client.put(
        "/api/v1/reports/summary/schedule",
        json={
            "is_active": True,
            "cadence": "monthly",
            "recipients": [f"persona{n}@clinicademo.com" for n in range(11)],
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reading_the_schedule_needs_the_write_permission(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """It carries the staff addresses, which is more than reading figures."""
    response = await client.get("/api/v1/reports/summary/schedule", headers=auth_headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_clinic_with_no_recipients_is_never_in_the_send_list(
    db_session, test_clinic: Clinic
) -> None:
    """Active with nobody to send to is not a reason to build a PDF."""
    await schedule.update(
        db_session, test_clinic.id, is_active=True, cadence="monthly", recipients=[]
    )
    assert await schedule.active_schedules(db_session) == []
