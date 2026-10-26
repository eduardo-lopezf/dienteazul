"""Load stable budget error codes from ``errors.json``."""

from __future__ import annotations

from typing import Final

from app.core.errors import (
    AppError,
    ErrorDefinition,
    error_raiser,
    load_error_catalog,
)

ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = load_error_catalog(__file__)

#: Raise one of this module's declared cases. See ``errors.json``.
budget_error = error_raiser(ERROR_CATALOG)


def budget_http_error(status_code: int, detail: str) -> AppError:
    """Assign a catalog code to an existing budget HTTP refusal."""
    known_codes = {
        "Budget not found": "budget.budget.not_found",
        "Budget item not found": "budget.item.not_found",
        "Budget has not been signed": "budget.signature.not_found",
        "Budget link not found": "budget.public_link.not_found",
        "Budget has not been accepted": "budget.public_link.not_accepted",
        "Patient not found": "budget.patient.not_found",
        "Professional not found in this clinic": "budget.professional.not_found",
        "Invalid method": "budget.public_link.invalid_method",
        "verification_required": "budget.public_link.verification_required",
        "locked": "budget.public_link.locked",
        "expired": "budget.public_link.expired",
        "rate_limited": "budget.public_link.rate_limited",
        "Budget already decided": "budget.public_link.already_decided",
        "Invalid reason": "budget.public_link.invalid_rejection_reason",
        "This budget belongs to a treatment plan and is deleted with the plan.": (
            "budget.budget.plan_owned"
        ),
        "Items can only be updated in draft budgets": "budget.budget.draft_required",
        "Reminders only apply to sent budgets": "budget.budget.reminder_not_sent",
        "Patient has no email address": "budget.patient.email_required",
        "Manual code must be 4-6 numeric digits": "budget.public_code.invalid",
        "The Patients app is not enabled: nothing new can be made for a patient": (
            "budget.patients.unavailable"
        ),
        "The treatment catalog is not enabled: lines cannot be added": (
            "budget.catalog.unavailable"
        ),
        "Professionals cannot be assigned: the Professionals app is not enabled": (
            "budget.professionals.unavailable"
        ),
        "Treatment plans are not available": "budget.plan.unavailable",
    }
    code = known_codes.get(detail)
    if code is None and (
        detail.startswith("Cannot send budget from status ")
        or detail.startswith("Cannot accept budget from status ")
        or detail.startswith("Cannot reject budget from status ")
        or detail.startswith("Cannot cancel budget from status ")
        or detail.startswith("Cannot renegotiate budget in status ")
    ):
        code = "budget.workflow.invalid_transition"
    elif code is None and detail in {"Cannot send empty budget", "Cannot accept empty budget"}:
        code = "budget.workflow.empty_budget"
    if code is None:
        if status_code == 404:
            code = "budget.budget.not_found"
        elif status_code == 401:
            code = "budget.public_link.verification_failed"
        elif status_code == 409:
            code = "budget.public_link.already_decided"
        elif status_code == 410:
            code = "budget.public_link.expired"
        elif status_code == 423:
            code = "budget.public_link.locked"
        elif status_code == 429:
            code = "budget.public_link.rate_limited"
        elif status_code == 422:
            code = "budget.request.invalid"
        else:
            code = "budget.request.operation_invalid"
    return budget_error(code, detail=detail)


def service_error(error: ValueError) -> AppError:
    """Translate legacy service validation errors at the HTTP boundary."""
    message = str(error)
    if message == "Professional not found in this clinic":
        code = "budget.professional.not_found"
    elif message == "Invalid catalog item":
        code = "budget.catalog_item.invalid"
    elif message == "An addendum needs a patient and at least one item":
        code = "budget.plan.addendum_data_required"
    elif message == "Only draft budgets can be edited":
        code = "budget.budget.draft_required"
    elif message in {
        "Items can only be added to draft budgets",
        "Items can only be removed from draft budgets",
    }:
        code = "budget.budget.draft_required"
    elif message == "Plan not found":
        code = "budget.plan.not_found"
    elif message == "Plan already has a budget linked":
        code = "budget.plan.already_linked"
    elif message == "No catalog items found in plan to create budget":
        code = "budget.plan.no_catalog_items"
    elif message == "Only a plan in progress can have an addendum":
        code = "budget.plan.addendum_invalid_status"
    elif message == "Every treatment in this plan is already budgeted":
        code = "budget.plan.treatments_already_budgeted"
    elif message.startswith("Treatment plans are not available"):
        code = "budget.plan.unavailable"
    elif message.startswith("Patients app is not enabled"):
        code = "budget.patients.unavailable"
    elif message.startswith("The treatment catalog is not enabled"):
        code = "budget.catalog.unavailable"
    elif message.startswith("Professionals cannot be assigned"):
        code = "budget.professionals.unavailable"
    else:
        code = "budget.request.operation_invalid"
    return budget_error(code, detail=message)


def workflow_error(error: Exception) -> AppError:
    """Translate budget workflow refusals to stable error codes."""
    message = str(error)
    if (
        message.startswith("Cannot send budget from status ")
        or message.startswith("Cannot accept budget from status ")
        or message.startswith("Cannot reject budget from status ")
        or message.startswith("Cannot cancel budget from status ")
        or message.startswith("Cannot renegotiate budget in status ")
    ):
        code = "budget.workflow.invalid_transition"
    elif message in {"Cannot send empty budget", "Cannot accept empty budget"}:
        code = "budget.workflow.empty_budget"
    elif message == "Patient has no email address":
        code = "budget.patient.email_required"
    elif message.startswith("Patients app is not enabled"):
        code = "budget.patients.unavailable"
    elif message == "Manual code must be 4-6 numeric digits":
        code = "budget.public_code.invalid"
    else:
        code = "budget.request.operation_invalid"
    return budget_error(code, detail=message)
