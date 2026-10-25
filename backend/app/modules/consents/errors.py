"""Load stable consent error codes from ``errors.json``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.errors import AppError, ErrorCategory

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


def consents_error(
    code: str,
    *,
    detail: str | None = None,
    fields: dict[str, Any] | None = None,
) -> AppError:
    definition = ERROR_CATALOG[code]
    return AppError(
        definition.code,
        status_code=definition.status_code,
        detail=detail or definition.message,
        category=definition.category,
        fields=fields,
    )


def consent_domain_error(message: str, *, state_error: bool = False) -> AppError:
    if state_error:
        code = "consents.consent.invalid_state"
    elif message.startswith("Professionals are not available"):
        code = "consents.professionals.unavailable"
    elif message == "Professional not found in this clinic":
        code = "consents.professional.not_found"
    elif message == "Patient not found in this clinic":
        code = "consents.patient.not_found"
    elif message == "Template not found for this kind of consent":
        code = "consents.template.invalid_for_kind"
    elif message == "A consent needs a title and a text":
        code = "consents.consent.content_required"
    elif message == "An informed consent must name the professional who explained it":
        code = "consents.consent.professional_required"
    elif message == "Documents are not available — a scan cannot be filed":
        code = "consents.documents.unavailable"
    elif message == "The scanned document is not one of this patient's files":
        code = "consents.scan.not_found"
    else:
        code = "consents.consent.invalid_state" if state_error else "consents.consent.invalid"
    return consents_error(code, detail=message)
