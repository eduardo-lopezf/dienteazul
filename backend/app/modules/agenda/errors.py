"""Load stable Agenda error codes from ``errors.json``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.errors import AppError, ErrorCategory

from .integrations import PATIENTS_UNAVAILABLE, PROFESSIONALS_UNAVAILABLE, TREATMENTS_UNAVAILABLE

ERRORS_FILE: Final[Path] = Path(__file__).with_name("errors.json")


class ErrorDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    category: ErrorCategory
    status_code: int = Field(ge=400, lt=600)
    message: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ErrorCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    errors: list[ErrorDefinition]

    @model_validator(mode="after")
    def _unique_codes(self) -> ErrorCatalog:
        codes = [error.code for error in self.errors]
        if len(codes) != len(set(codes)):
            raise ValueError("error codes must be unique")
        return self


def _load_catalog() -> dict[str, ErrorDefinition]:
    data = json.loads(ERRORS_FILE.read_text(encoding="utf-8"))
    catalog = ErrorCatalog.model_validate(data)
    return {error.code: error for error in catalog.errors}


# Fail at startup if the module's error contract is malformed.
ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = _load_catalog()


def agenda_error(code: str, *, detail: str | None = None) -> AppError:
    definition = ERROR_CATALOG[code]
    return AppError(
        definition.code,
        status_code=definition.status_code,
        detail=detail or definition.message,
        category=definition.category,
    )


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
