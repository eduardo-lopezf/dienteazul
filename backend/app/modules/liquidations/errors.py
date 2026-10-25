"""Load stable liquidations error codes from ``errors.json``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

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


def liquidation_error(code: str, *, detail: str | None = None) -> AppError:
    definition = ERROR_CATALOG[code]
    return AppError(
        definition.code,
        status_code=definition.status_code,
        detail=detail or definition.message,
        category=definition.category,
    )


def service_error(error: ValueError) -> AppError:
    """Translate liquidation service refusals to stable error codes."""
    message = str(error)
    if message == "That professional is not in this clinic.":
        code = "liquidations.professional.not_found"
    elif message.startswith("Settlements cannot be calculated:"):
        code = "liquidations.apps.unavailable"
    elif message == "The period ends before it starts.":
        code = "liquidations.period.invalid"
    elif message == "This period has already been settled with this professional.":
        code = "liquidations.settlement.already_issued"
    elif message.startswith("There is no agreed percentage for this professional yet."):
        code = "liquidations.commission.required"
    elif message == "This settlement has already been paid.":
        code = "liquidations.settlement.already_paid"
    elif message == "This settlement has not been paid.":
        code = "liquidations.settlement.not_paid"
    elif message.startswith("The till movement for this payout belongs to a day that"):
        code = "liquidations.cashbox.closing_conflict"
    else:
        code = "liquidations.operation.invalid"
    return liquidation_error(code, detail=message)
