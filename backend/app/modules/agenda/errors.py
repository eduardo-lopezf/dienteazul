"""Load stable Agenda error codes from ``errors.json``."""

from __future__ import annotations

from typing import Final

from app.core.errors import (
    AppError,
    ErrorDefinition,
    error_raiser,
    load_error_catalog,
)

from .integrations import PATIENTS_UNAVAILABLE, PROFESSIONALS_UNAVAILABLE, TREATMENTS_UNAVAILABLE

ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = load_error_catalog(__file__)

#: Raise one of this module's declared cases. See ``errors.json``.
agenda_error = error_raiser(ERROR_CATALOG)


def service_error(error: ValueError) -> AppError:
    """Translate legacy service validation errors at the HTTP boundary."""
    message = str(error)
    integrations = {
        PATIENTS_UNAVAILABLE: "agenda.patients.unavailable",
        PROFESSIONALS_UNAVAILABLE: "agenda.professionals.unavailable",
        TREATMENTS_UNAVAILABLE: "agenda.treatments.unavailable",
    }
    if message in integrations:
        return agenda_error(integrations[message])
    if message.startswith("Cabinet not found:"):
        return agenda_error("agenda.cabinet.not_found")
    if message == "A professional is required":
        return agenda_error("agenda.professional.required")
    return agenda_error("agenda.appointment.invalid", detail=message)
