"""Load stable memberships error codes from ``errors.json``."""

from __future__ import annotations

from typing import Final

from app.core.errors import AppError, ErrorDefinition, error_raiser, load_error_catalog

ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = load_error_catalog(__file__)

#: Raise one of this module's declared cases. See ``errors.json``.
membership_error = error_raiser(ERROR_CATALOG)

_CODES: Final[dict[str, str]] = {
    "That plan is not in this clinic.": "memberships.plan.not_found",
    "That plan is archived.": "memberships.plan.archived",
    "A treatment can only appear once in a plan.": "memberships.benefit.duplicate",
    "That treatment is not in this clinic's catalogue.": "memberships.treatment.not_found",
    "Benefits need the Treatments app.": "memberships.apps.unavailable",
    "That patient is not in this clinic.": "memberships.patient.not_found",
    "That membership is not in this clinic.": "memberships.membership.not_found",
    "The patient already has an active membership.": "memberships.membership.exists",
    "That membership is cancelled.": "memberships.membership.cancelled",
}


def service_error(error: ValueError) -> AppError:
    """Translate membership service refusals to stable error codes."""
    message = str(error)
    return membership_error(_CODES.get(message, "memberships.operation.invalid"), detail=message)
