"""Load stable patients_clinical error codes from ``errors.json``."""

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


def record_not_found(resource: str) -> AppError:
    return _app_error(f"patients_clinical.{resource}.not_found")


def rejected(resource: str, reason: str) -> AppError:
    return _app_error(f"patients_clinical.{resource}.rejected", detail=reason)
