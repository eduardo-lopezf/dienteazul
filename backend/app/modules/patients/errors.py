"""Load the stable, module-owned error codes from ``errors.json``."""

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
_app_error = error_raiser(ERROR_CATALOG)


def patient_not_found() -> AppError:
    return _app_error("patients.patient.not_found")


def invalid_patient_sort() -> AppError:
    return _app_error("patients.patient.invalid_sort")
