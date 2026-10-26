"""Load stable notification error codes from ``errors.json``."""

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
notifications_error = error_raiser(ERROR_CATALOG)


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
