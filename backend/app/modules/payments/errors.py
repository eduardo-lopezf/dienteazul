"""Load stable payment error codes from ``errors.json``."""

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
payments_error = error_raiser(ERROR_CATALOG)


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
