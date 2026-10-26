"""Load stable liquidations error codes from ``errors.json``."""

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
liquidation_error = error_raiser(ERROR_CATALOG)


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
