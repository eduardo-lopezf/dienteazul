"""Load stable treatment-plan error codes from ``errors.json``."""

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


def treatment_plan_error(
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


def service_error(error: ValueError, *, resource: str) -> AppError:
    """Map common service-layer refusals while preserving their detail."""
    message = str(error)
    not_found_codes = {
        "Plan not found": "treatment_plan.plan.not_found",
        "Treatment plan not found": "treatment_plan.plan.not_found",
        "Treatment item not found": "treatment_plan.item.not_found",
        "Session not found": "treatment_plan.session.not_found",
        "Template not found": "treatment_plan.template.not_found",
    }
    if message in not_found_codes:
        return treatment_plan_error(not_found_codes[message], detail=message)
    if message.startswith("Invalid status transition"):
        return treatment_plan_error("treatment_plan.plan.invalid_transition", detail=message)
    if message == "Invalid patient":
        return treatment_plan_error("treatment_plan.patient.invalid", detail=message)
    if message == "Invalid professional for this clinic":
        return treatment_plan_error("treatment_plan.professional.invalid", detail=message)
    if message == "Professional not found":
        return treatment_plan_error(
            "treatment_plan.prescription.professional_invalid", detail=message
        )
    if message.startswith("Professionals are not available"):
        return treatment_plan_error("treatment_plan.professionals.unavailable", detail=message)
    if message.startswith("Budgets are not available"):
        return treatment_plan_error("treatment_plan.budgets.unavailable", detail=message)
    if message in {"Invalid budget", "Budget belongs to different patient"}:
        return treatment_plan_error("treatment_plan.budget.invalid", detail=message)
    return treatment_plan_error(f"treatment_plan.{resource}.invalid", detail=message)
