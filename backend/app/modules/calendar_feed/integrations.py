"""What this module reads, and whether it can.

The agenda owns the appointments and the professionals directory owns
who the user is in this clinic. Neither is imported: both are asked for
through the core contracts (ADR 0039), and ``None`` means that App is
off — in which case there is nothing to publish and the feed says so
instead of serving an empty calendar (ADR 0037).
"""

from __future__ import annotations

from app.core.contracts import AppointmentBook, ProfessionalDirectory, provider

AGENDA_UNAVAILABLE = "The calendar feed needs the Agenda app, which is not enabled"


def appointments() -> AppointmentBook | None:
    return provider(AppointmentBook)


def professionals() -> ProfessionalDirectory | None:
    return provider(ProfessionalDirectory)


def agenda_available() -> bool:
    return appointments() is not None
