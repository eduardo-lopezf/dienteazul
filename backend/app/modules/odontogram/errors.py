"""Load stable odontogram error codes from ``errors.json``."""

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


def odontogram_error(
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


def treatment_service_error(error: ValueError) -> AppError:
    """Map known treatment-domain refusals while preserving their details."""
    message = str(error)
    if message == "Catalog item not found":
        code = "odontogram.treatment.catalog_item_not_found"
    elif message.startswith("clinical_type=") and "conflicts with catalog mapping" in message:
        code = "odontogram.treatment.catalog_mapping_conflict"
    elif message == "clinical_type is required when no catalog item is given":
        code = "odontogram.treatment.clinical_type_required"
    elif message == "bridge requires at least one pillar tooth":
        code = "odontogram.treatment.bridge_requires_pillar"
    elif "is for " in message and " teeth only; not on tooth " in message:
        code = "odontogram.treatment.dentition_mismatch"
    elif message.startswith("clinical_type=") and "requires at least 2 teeth" in message:
        code = "odontogram.treatment.atomic_tooth_count_invalid"
    else:
        code = "odontogram.treatment.invalid"
    return odontogram_error(code, detail=message)
