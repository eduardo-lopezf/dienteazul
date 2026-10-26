"""Load stable recalls error codes from ``errors.json``."""

from __future__ import annotations

from typing import Final

from app.core.errors import (
    AppError,
    ErrorDefinition,
    error_raiser,
    load_error_catalog,
)
from app.modules.recalls.service import PROFESSIONALS_UNAVAILABLE

ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = load_error_catalog(__file__)

#: Raise one of this module's declared cases. See ``errors.json``.
recalls_error = error_raiser(ERROR_CATALOG)


def service_error(error: ValueError) -> AppError:
    """Translate recall service refusals to stable error codes."""
    message = str(error)
    if message == "Patient not found in this clinic":
        code = "recalls.patient.not_found"
    elif message == "Professional not found in this clinic":
        code = "recalls.professional.not_found"
    elif message == PROFESSIONALS_UNAVAILABLE:
        code = "recalls.professionals.unavailable"
    else:
        code = "recalls.operation.invalid"
    return recalls_error(code, detail=message)
