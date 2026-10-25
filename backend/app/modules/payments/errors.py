"""Load stable payment error codes from ``errors.json``."""

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


def payments_error(
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


def workflow_error(message: str) -> AppError:
    if message.startswith("Budget ") and message.endswith(" not found"):
        code = "payments.budget.not_found"
    elif message.startswith("Budget ") and message.endswith(" belongs to another clinic"):
        code = "payments.budget.wrong_clinic"
    elif message == "At least one allocation required":
        code = "payments.payment.allocation_required"
    elif (
        message.startswith("Allocations sum ")
        or message == "New allocations must sum to payment.amount"
    ):
        code = "payments.payment.allocation_sum_mismatch"
    elif message == "Refund amount must be > 0":
        code = "payments.refund.invalid_amount"
    elif message.startswith("Refund ") and " exceeds remaining cap " in message:
        code = "payments.refund.exceeds_payment"
    elif message.startswith("Patients are not available"):
        code = "payments.patients.unavailable"
    else:
        code = "payments.payment.invalid"
    return payments_error(code, detail=message)


def schedule_error(message: str) -> AppError:
    if message == "A schedule needs at least one instalment":
        code = "payments.schedule.instalment_required"
    elif message == "Instalment amounts must be greater than zero":
        code = "payments.schedule.instalment_amount_invalid"
    else:
        code = "payments.schedule.invalid"
    return payments_error(code, detail=message)
