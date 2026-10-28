"""Render appointments as an iCalendar (RFC 5545) document.

A pure function over :class:`AppointmentEntry` — plain data the agenda
handed over, never its rows (ADR 0039). A patient whose App is off has
no name in the entry and therefore none in the event either (ADR 0037).

Two things in here are not optional:

- **Times go out in UTC.** ``start_time`` / ``end_time`` are the
  clinic's wall clock and the offset they carry is a storage artifact,
  so the hands are read off naively and localized to the clinic's zone
  before being converted. Emitting the stored instant is how an
  appointment ends up two hours out on a subscriber's phone.
- **Every value is escaped and every line folded.** A patient called
  ``Ruiz, Ana`` or a note with a newline in it breaks the document for
  every client reading it, not just that one event.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.core.contracts import AppointmentEntry

PRODID = "-//Diente Azul//Calendar Feed//ES"

#: How often a client is asked to come back. A suggestion, not a
#: contract: Google honours it loosely and polls a few times a day.
REFRESH_INTERVAL = "PT1H"

#: iCalendar has three event states; the agenda has seven.
_STATUS: dict[str, str] = {
    "scheduled": "TENTATIVE",
    "confirmed": "CONFIRMED",
    "checked_in": "CONFIRMED",
    "in_treatment": "CONFIRMED",
    "completed": "CONFIRMED",
    "no_show": "CANCELLED",
    "cancelled": "CANCELLED",
}

#: What an appointment with neither patient nor title is called.
UNTITLED = "Cita"


def _escape(value: str) -> str:
    """Escape a TEXT value (RFC 5545 §3.3.11). Backslash goes first."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Fold a content line at 75 octets, continuing with one space.

    Counted in octets, not characters: a name with accents is longer on
    the wire than it looks, and a cut inside a UTF-8 sequence produces a
    character no client can decode.
    """
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    chunks: list[bytes] = []
    start = 0
    limit = 75
    while start < len(raw):
        end = min(start + limit, len(raw))
        # Never split a multi-byte sequence: back off to a lead byte.
        while end < len(raw) and raw[end] & 0xC0 == 0x80:
            end -= 1
        chunks.append(raw[start:end])
        start = end
        limit = 74  # continuation lines spend one octet on the leading space
    head, *rest = (chunk.decode("utf-8") for chunk in chunks)
    return "\r\n ".join([head, *rest])


def _utc(moment: datetime, tz: ZoneInfo) -> str:
    """Format a stored wall clock as a UTC instant."""
    wall = moment.replace(tzinfo=None)
    return wall.replace(tzinfo=tz).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _stamp(moment: datetime) -> str:
    """Format a real instant (``updated_at`` and friends) as UTC."""
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _summary(entry: AppointmentEntry) -> str:
    """What the subscriber reads in their calendar.

    The patient names the appointment; ``title`` names one that has no
    patient, and the treatment follows when it adds something.
    """
    who = entry.patient_name or entry.title or UNTITLED
    return f"{who} · {entry.treatment_type}" if entry.treatment_type else who


def _description(entry: AppointmentEntry) -> str | None:
    lines = [entry.professional_name] if entry.professional_name else []
    lines.extend(f"- {name}" for name in entry.treatment_names)
    return "\n".join(lines) if lines else None


def _event(entry: AppointmentEntry, tz: ZoneInfo, domain: str) -> list[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{entry.id}@{domain}",
        f"DTSTAMP:{_stamp(entry.updated_at)}",
        f"DTSTART:{_utc(entry.start_time, tz)}",
        f"DTEND:{_utc(entry.end_time, tz)}",
        f"SUMMARY:{_escape(_summary(entry))}",
        f"STATUS:{_STATUS.get(entry.status, 'CONFIRMED')}",
        "TRANSP:OPAQUE",
        f"LAST-MODIFIED:{_stamp(entry.updated_at)}",
    ]
    if entry.cabinet:
        lines.append(f"LOCATION:{_escape(entry.cabinet)}")
    description = _description(entry)
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    lines.append("END:VEVENT")
    return lines


def render(
    entries: Sequence[AppointmentEntry],
    *,
    calendar_name: str,
    timezone: str,
    domain: str = "dienteazul",
) -> str:
    """The whole document, CRLF-terminated as the spec requires."""
    tz = ZoneInfo(timezone)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
        f"X-WR-TIMEZONE:{timezone}",
        f"REFRESH-INTERVAL;VALUE=DURATION:{REFRESH_INTERVAL}",
        f"X-PUBLISHED-TTL:{REFRESH_INTERVAL}",
    ]
    for entry in entries:
        lines.extend(_event(entry, tz, domain))
    lines.append("END:VCALENDAR")
    return "".join(f"{_fold(line)}\r\n" for line in lines)
