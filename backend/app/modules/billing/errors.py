"""Load stable billing error codes from ``errors.json``."""

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


def billing_error(
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
    """Map service-layer validation failures to stable billing codes."""
    message = str(error)
    if message == "Patient not found":
        code = "billing.invoice.patient_not_found"
    elif message == "Budget not found":
        code = "billing.budget.not_found"
    elif message.startswith("Budget item ") and message.endswith(" not found"):
        code = "billing.budget_item.not_found"
    elif message.startswith("Budget item ") and message.endswith(" is fully invoiced"):
        code = "billing.budget_item.fully_invoiced"
    elif message.startswith("Requested quantity (") and " exceeds available (" in message:
        code = "billing.budget_item.quantity_exceeded"
    elif message.startswith("Series ") and message.endswith(" not found"):
        code = "billing.series.not_configured"
    elif message.startswith("Series ") and message.endswith(" is not active"):
        code = "billing.series.inactive"
    elif message == "Can only edit draft invoices":
        code = "billing.invoice.draft_required"
    elif message == "Cannot change patient for invoice linked to a budget":
        code = "billing.invoice.patient_change_forbidden"
    elif message.startswith("Cannot invoice budget with status "):
        code = "billing.budget.status_invalid"
    elif message.startswith("New number must be greater than "):
        code = "billing.series.reset_number_invalid"
    else:
        code = f"billing.{resource}.invalid"
    return billing_error(code, detail=message)


def workflow_error(error: Exception, *, operation: str) -> AppError:
    """Map workflow refusals to stable codes without hiding their details."""
    message = str(error)
    if operation == "billing_party" and "concurrent edit detected" in message.lower():
        code = "billing.invoice.concurrent_edit"
    elif operation == "billing_party" and message.startswith("Cannot edit billing party"):
        code = "billing.invoice.billing_party_status_invalid"
    elif operation == "billing_party":
        code = "billing.invoice.billing_party_invalid"
    elif message.startswith("Patients are not available"):
        code = "billing.patients.unavailable"
    elif message.startswith("No default ") and message.endswith(" series configured"):
        code = "billing.series.default_missing"
    elif "concurrent edit detected" in message.lower():
        code = "billing.invoice.concurrent_edit"
    elif message == "Cannot issue empty invoice":
        code = "billing.invoice.empty"
    elif message.startswith("Cannot issue invoice: incomplete billing data."):
        code = "billing.invoice.billing_data_incomplete"
    elif message.endswith(" not found in original invoice"):
        code = "billing.credit_note.item_not_found"
    elif message.startswith("Credit note quantity (") and " exceeds original (" in message:
        code = "billing.credit_note.quantity_exceeded"
    elif message.startswith("Cannot issue invoice from status "):
        code = "billing.invoice.issue_status_invalid"
    elif message.startswith("Cannot void invoice from status "):
        code = "billing.invoice.void_status_invalid"
    elif message.startswith("Cannot create credit note for invoice with status "):
        code = "billing.credit_note.status_invalid"
    elif "Field '" in message and message.endswith("' is required"):
        code = "billing.invoice.compliance_field_required"
    else:
        code = f"billing.{operation}.invalid"
    return billing_error(code, detail=message)
