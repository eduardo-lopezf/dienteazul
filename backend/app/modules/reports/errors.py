"""Load stable reports error codes from ``errors.json``."""

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
reports_error = error_raiser(ERROR_CATALOG)


def service_error(error: ValueError) -> AppError:
    """Translate report service validation errors to stable codes."""
    message = str(error)
    if message == "date_to must be on or after date_from":
        code = "reports.date_range.invalid"
    elif message.startswith("date range exceeds "):
        code = "reports.date_range.too_long"
    else:
        code = "reports.request.invalid"
    return reports_error(code, detail=message)
