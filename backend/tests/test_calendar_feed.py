"""The calendar subscription (ADR 0061).

Covers what the feed promises: nothing is served without a live token,
the times are the clinic's wall clock expressed as UTC instants, and a
value that would break the document is escaped instead of emitted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.contracts import AppointmentEntry
from app.modules.agenda.models import Appointment
from app.modules.calendar_feed import ics
from app.modules.calendar_feed.models import CalendarFeed

#: 09:30 of the clinic's wall clock, stored with whatever offset the
#: writer happened to carry — that offset is the artifact the renderer
#: must ignore.
WALL = datetime(2026, 7, 15, 9, 30, tzinfo=UTC)

SUBSCRIPTION = "/api/v1/calendar_feed/subscription"


def _entry(**extra) -> AppointmentEntry:
    payload = {
        "id": uuid4(),
        "start_time": WALL,
        "end_time": WALL + timedelta(minutes=30),
        "status": "confirmed",
        "updated_at": datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
    }
    payload.update(extra)
    return AppointmentEntry(**payload)


async def _issue(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    response = await client.post(SUBSCRIPTION, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]["token"]


# --- The document -------------------------------------------------------


def test_wall_clock_is_rendered_as_the_clinics_instant() -> None:
    """09:30 in Madrid is 07:30Z in July. Emitting the stored instant
    instead is how an appointment lands two hours out on a phone."""
    document = ics.render([_entry()], calendar_name="Clínica", timezone="Europe/Madrid")

    assert "DTSTART:20260715T073000Z" in document
    assert "DTEND:20260715T080000Z" in document


def test_a_comma_in_a_patients_name_does_not_break_the_document() -> None:
    document = ics.render(
        [_entry(patient_name="Ana Ruiz, Pérez")],
        calendar_name="Clínica",
        timezone="Europe/Madrid",
    )

    assert "SUMMARY:Ana Ruiz\\, Pérez" in document


def test_a_newline_in_a_treatment_name_does_not_break_the_document() -> None:
    document = ics.render(
        [_entry(professional_name="Dra. Ruiz", treatment_names=("Empaste\nsuperior",))],
        calendar_name="Clínica",
        timezone="Europe/Madrid",
    )

    assert "DESCRIPTION:Dra. Ruiz\\n- Empaste\\nsuperior" in document


def test_long_lines_are_folded_without_splitting_a_character() -> None:
    document = ics.render(
        [_entry(title="Á" * 90)], calendar_name="Clínica", timezone="Europe/Madrid"
    )

    for line in document.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    # Folded or not, the text survives the round trip.
    assert "Á" * 90 in document.replace("\r\n ", "")


def test_the_patient_names_the_event_and_the_title_stands_in() -> None:
    named = ics.render(
        [_entry(patient_name="Ana Ruiz", treatment_type="Revisión")],
        calendar_name="C",
        timezone="Europe/Madrid",
    )
    titled = ics.render([_entry(title="Bloqueo")], calendar_name="C", timezone="Europe/Madrid")
    bare = ics.render([_entry()], calendar_name="C", timezone="Europe/Madrid")

    assert "SUMMARY:Ana Ruiz · Revisión" in named
    assert "SUMMARY:Bloqueo" in titled
    assert f"SUMMARY:{ics.UNTITLED}" in bare


def test_a_booked_appointment_is_tentative_until_confirmed() -> None:
    document = ics.render(
        [_entry(status="scheduled"), _entry(status="no_show")],
        calendar_name="C",
        timezone="Europe/Madrid",
    )

    assert "STATUS:TENTATIVE" in document
    assert "STATUS:CANCELLED" in document


def test_the_envelope_is_what_a_calendar_client_expects() -> None:
    document = ics.render([], calendar_name="Clínica Azul", timezone="Europe/Madrid")

    assert document.startswith("BEGIN:VCALENDAR\r\n")
    assert document.endswith("END:VCALENDAR\r\n")
    assert "X-WR-CALNAME:Clínica Azul" in document
    assert "X-WR-TIMEZONE:Europe/Madrid" in document


# --- The endpoints ------------------------------------------------------


@pytest.mark.asyncio
async def test_reading_the_subscription_does_not_create_one(
    client: AsyncClient, test_clinic: Clinic, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A URL that carries patient names out of the clinic is asked for."""
    response = await client.get(SUBSCRIPTION, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["data"] is None
    assert (await db_session.execute(select(CalendarFeed))).scalars().all() == []


@pytest.mark.asyncio
async def test_the_token_is_unguessable_and_not_a_uuid7(
    client: AsyncClient, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    """A uuid7's timestamp prefix is readable; a credential must not be
    (ADR 0056 carves out exactly this case)."""
    response = await client.post(SUBSCRIPTION, headers=auth_headers)

    data = response.json()["data"]
    assert UUID(data["token"]).version == 4
    assert data["path"] == f"/api/v1/calendar_feed/calendar/{data['token']}.ics"


@pytest.mark.asyncio
async def test_the_feed_serves_the_clinics_appointments(
    client: AsyncClient,
    test_clinic: Clinic,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    start = datetime.now(UTC) + timedelta(days=3)
    db_session.add(
        Appointment(
            id=uuid4(),
            clinic_id=test_clinic.id,
            title="Revisión",
            start_time=start,
            end_time=start + timedelta(minutes=30),
            status="confirmed",
        )
    )
    await db_session.commit()
    token = await _issue(client, auth_headers)

    response = await client.get(f"/api/v1/calendar_feed/calendar/{token}.ics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "SUMMARY:Revisión" in response.text


@pytest.mark.asyncio
async def test_a_cancelled_appointment_is_not_published(
    client: AsyncClient,
    test_clinic: Clinic,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    start = datetime.now(UTC) + timedelta(days=4)
    db_session.add(
        Appointment(
            id=uuid4(),
            clinic_id=test_clinic.id,
            title="Anulada",
            start_time=start,
            end_time=start + timedelta(minutes=30),
            status="cancelled",
        )
    )
    await db_session.commit()
    token = await _issue(client, auth_headers)

    response = await client.get(f"/api/v1/calendar_feed/calendar/{token}.ics")

    assert "Anulada" not in response.text


@pytest.mark.asyncio
async def test_an_appointment_outside_the_window_is_not_published(
    client: AsyncClient,
    test_clinic: Clinic,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    start = datetime.now(UTC) + timedelta(days=400)
    db_session.add(
        Appointment(
            id=uuid4(),
            clinic_id=test_clinic.id,
            title="Muy lejana",
            start_time=start,
            end_time=start + timedelta(minutes=30),
            status="confirmed",
        )
    )
    await db_session.commit()
    token = await _issue(client, auth_headers)

    response = await client.get(f"/api/v1/calendar_feed/calendar/{token}.ics")

    assert "Muy lejana" not in response.text


@pytest.mark.asyncio
async def test_another_clinics_appointment_is_never_published(
    client: AsyncClient,
    test_clinic: Clinic,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """The feed is scoped to the clinic the subscription belongs to."""
    other = Clinic(
        id=uuid4(),
        name="Otra Clínica",
        tax_id="B99999999",
        address={"city": "Madrid"},
        settings={},
        account_tier="clinic",
    )
    db_session.add(other)
    await db_session.flush()
    start = datetime.now(UTC) + timedelta(days=2)
    db_session.add(
        Appointment(
            id=uuid4(),
            clinic_id=other.id,
            title="Ajena",
            start_time=start,
            end_time=start + timedelta(minutes=30),
            status="confirmed",
        )
    )
    await db_session.commit()
    token = await _issue(client, auth_headers)

    response = await client.get(f"/api/v1/calendar_feed/calendar/{token}.ics")

    assert "Ajena" not in response.text


@pytest.mark.asyncio
async def test_a_dead_token_is_a_bare_404(
    client: AsyncClient, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    """Rotating is revoking: the URL already pasted into a phone stops
    resolving, and says nothing about why."""
    first = await _issue(client, auth_headers)
    second = await _issue(client, auth_headers)

    assert first != second
    assert (await client.get(f"/api/v1/calendar_feed/calendar/{first}.ics")).status_code == 404
    assert (await client.get("/api/v1/calendar_feed/calendar/not-a-uuid.ics")).status_code == 404
    assert (await client.get(f"/api/v1/calendar_feed/calendar/{uuid4()}.ics")).status_code == 404


@pytest.mark.asyncio
async def test_revoking_stops_answering(
    client: AsyncClient, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    token = await _issue(client, auth_headers)

    assert (await client.delete(SUBSCRIPTION, headers=auth_headers)).status_code == 204
    assert (await client.get(f"/api/v1/calendar_feed/calendar/{token}.ics")).status_code == 404
    assert (await client.delete(SUBSCRIPTION, headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_a_poll_records_that_the_subscription_is_alive(
    client: AsyncClient,
    test_clinic: Clinic,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    token = await _issue(client, auth_headers)

    await client.get(f"/api/v1/calendar_feed/calendar/{token}.ics")

    feed = (
        await db_session.execute(select(CalendarFeed).where(CalendarFeed.token == UUID(token)))
    ).scalar_one()
    await db_session.refresh(feed)
    assert feed.last_access_at is not None
    assert (await client.get(SUBSCRIPTION, headers=auth_headers)).json()["data"][
        "last_access_at"
    ] is not None


@pytest.mark.asyncio
async def test_the_subscription_endpoint_needs_a_session(
    client: AsyncClient, test_clinic: Clinic
) -> None:
    assert (await client.get(SUBSCRIPTION)).status_code == 401
