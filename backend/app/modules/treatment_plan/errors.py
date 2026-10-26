"""Load stable treatment-plan error codes from ``errors.json``."""

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
treatment_plan_error = error_raiser(ERROR_CATALOG)


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
