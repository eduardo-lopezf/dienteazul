"""Load stable notification error codes from ``errors.json``."""

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


def notifications_error(
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


def notifications_http_error(status_code: int, detail: str) -> AppError:
    """Map existing route refusals to the notification error contract."""
    normalized = detail.lower()
    if status_code == 404 and "template" in normalized:
        code = "notifications.template.not_found"
    elif status_code == 409 and "template" in normalized:
        code = "notifications.template.already_exists"
    elif status_code == 403 and "system template" in normalized:
        code = "notifications.template.system_read_only"
    elif status_code == 403 and "other clinics" in normalized:
        code = "notifications.template.other_clinic"
    elif status_code == 404 and "patient" in normalized:
        code = "notifications.patient.not_found"
    elif status_code == 404 and "appointment" in normalized:
        code = "notifications.appointment.not_found"
    elif status_code == 404 and "budget" in normalized:
        code = "notifications.budget.not_found"
    elif status_code == 400 and "patients" in normalized:
        code = "notifications.patients.unavailable"
    elif status_code == 400 and "agenda" in normalized:
        code = "notifications.agenda.unavailable"
    elif status_code == 400 and "budget" in normalized and "enabled" in normalized:
        code = "notifications.budget.unavailable"
    elif status_code == 400 and "email" in normalized and "patient" in normalized:
        code = "notifications.patient.email_missing"
    elif status_code == 400 and "appointment_id" in normalized:
        code = "notifications.appointment.id_required"
    elif status_code == 400 and "budget_id" in normalized:
        code = "notifications.budget.id_required"
    elif status_code == 400 and "recipient email" in normalized:
        code = "notifications.recipient.email_unavailable"
    elif status_code == 409 and ("24h" in normalized or "free-form" in normalized):
        code = "notifications.conversation.reply_unavailable"
    else:
        code = (
            "notifications.request.invalid"
            if status_code == 422
            else "notifications.request.operation_invalid"
        )
    return notifications_error(code, detail=detail)


def service_error(error: ValueError) -> AppError:
    """Translate service validation failures to stable notification codes."""
    message = str(error)
    if message == "Cannot modify system templates" or message == "Cannot delete system templates":
        code = "notifications.template.system_read_only"
    elif message.startswith("Patient ") and " is not in clinic " in message:
        code = "notifications.patient.not_found"
    elif "Patients app" in message:
        code = "notifications.patients.unavailable"
    else:
        code = "notifications.request.operation_invalid"
    return notifications_error(code, detail=message)
