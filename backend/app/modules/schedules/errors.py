"""Load stable schedules error codes from ``errors.json``."""

from __future__ import annotations

from typing import Final

from app.core.errors import (
    AppError,
    ErrorDefinition,
    error_raiser,
    load_error_catalog,
)

ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = load_error_catalog(__file__)

#: Raise one of this module's declared cases. See ``errors.json``.
schedules_error = error_raiser(ERROR_CATALOG)


def schedules_http_error(status_code: int, detail: str) -> AppError:
    """Map existing schedule route refusals to the schedules catalog."""
    normalized = detail.lower()
    if status_code == 403:
        code = "schedules.professional.access_denied"
    elif status_code == 404 and "professional" in normalized:
        code = "schedules.professional.not_found"
    elif status_code == 404:
        code = "schedules.override.not_found"
    elif "end must be on or after start" in normalized:
        code = "schedules.date_range.invalid"
    else:
        code = "schedules.request.invalid"
    return schedules_error(code, detail=detail)
