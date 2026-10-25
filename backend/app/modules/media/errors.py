"""Load stable media error codes from ``errors.json``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from fastapi import status
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

DOCUMENT_NOT_FOUND: Final[str] = "media.document.not_found"
ATTACHMENT_NOT_FOUND: Final[str] = "media.attachment.not_found"
PATIENT_NOT_FOUND: Final[str] = "media.patient.not_found"
OWNER_NOT_FOUND: Final[str] = "media.owner.not_found"
WRONG_PATIENT: Final[str] = "media.document.wrong_patient"
FILE_TOO_LARGE: Final[str] = "media.file.too_large"
FILE_TYPE_NOT_ALLOWED: Final[str] = "media.file.type_not_allowed"
DOCUMENT_TYPE_INVALID: Final[str] = "media.document.invalid_type"
PHOTO_TAXONOMY_INVALID: Final[str] = "media.photo.invalid_taxonomy"
DOCUMENT_SELF_PAIR: Final[str] = "media.document.self_pair"
ATTACHMENT_OWNER_TYPE_INVALID: Final[str] = "media.attachment.owner_type_invalid"


def media_error(code: str, *, status_code: int, detail: str) -> AppError:
    definition = ERROR_CATALOG[code]
    if status_code != definition.status_code:
        raise ValueError(f"status mismatch for {code}: {status_code} != {definition.status_code}")
    return AppError(
        definition.code,
        status_code=definition.status_code,
        detail=detail,
        category=definition.category,
    )


def not_found(code: str, detail: str) -> AppError:
    return media_error(code, status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def invalid(code: str, detail: str) -> AppError:
    return media_error(code, status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
