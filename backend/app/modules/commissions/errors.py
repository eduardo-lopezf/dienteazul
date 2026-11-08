"""Load stable commissions error codes from ``errors.json``."""

from __future__ import annotations

from typing import Final

from app.core.errors import AppError, ErrorDefinition, error_raiser, load_error_catalog

ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = load_error_catalog(__file__)

#: Raise one of this module's declared cases. See ``errors.json``.
commission_error = error_raiser(ERROR_CATALOG)

_CODES: Final[dict[str, str]] = {
    "That professional is not in this clinic.": "commissions.professional.not_found",
    "Commissions are only available to clinics.": "commissions.tier.unavailable",
    "A treatment can only carry one percentage.": "commissions.rate.duplicate",
    "That treatment is not in this clinic's catalogue.": "commissions.treatment.not_found",
    "Treatment rates need the Treatments app.": "commissions.apps.unavailable",
}


def service_error(error: ValueError) -> AppError:
    """Translate commission service refusals to stable error codes."""
    message = str(error)
    return commission_error(_CODES.get(message, "commissions.operation.invalid"), detail=message)
