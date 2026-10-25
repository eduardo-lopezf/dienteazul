"""Load stable cashbox error codes from ``errors.json``."""

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


def cashbox_error(
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


def service_error(error: ValueError) -> AppError:
    """Translate cashbox service refusals to stable error codes."""
    message = str(error)
    if "payout of a settlement" in message:
        code = "cashbox.movement.settlement_payout"
    elif "belongs to a closed day" in message:
        code = "cashbox.movement.closed_day"
    elif "future" in message and "counted" in message:
        code = "cashbox.closing.future_date"
    elif "already counted" in message:
        code = "cashbox.closing.already_closed"
    elif "does not match the expected cash" in message:
        code = "cashbox.closing.difference_notes_required"
    elif "More cash cannot be left" in message:
        code = "cashbox.closing.float_exceeds_count"
    elif "already been superseded" in message:
        code = "cashbox.closing.already_superseded"
    elif message.startswith("Unknown period kind:"):
        code = "cashbox.period.kind_invalid"
    elif "entry has already been dealt with" in message:
        code = "cashbox.late_entry.already_acknowledged"
    else:
        code = "cashbox.request.invalid"
    return cashbox_error(code, detail=message)
