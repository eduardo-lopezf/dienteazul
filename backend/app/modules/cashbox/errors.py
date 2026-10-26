"""Load stable cashbox error codes from ``errors.json``."""

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
cashbox_error = error_raiser(ERROR_CATALOG)


def service_error(error: ValueError) -> AppError:
    """Translate cashbox service refusals to stable error codes."""
    message = str(error)
    if "payout of a settlement" in message:
        code = "cashbox.movement.settlement_payout"
    elif "belongs to a closed day" in message:
        code = "cashbox.movement.closed_day"
    elif "future" in message and "counted" in message:
        code = "cashbox.closing.future_date"
    elif "already counted" in message:
        code = "cashbox.closing.already_closed"
    elif "does not match the expected cash" in message:
        code = "cashbox.closing.difference_notes_required"
    elif "More cash cannot be left" in message:
        code = "cashbox.closing.float_exceeds_count"
    elif "already been superseded" in message:
        code = "cashbox.closing.already_superseded"
    elif message.startswith("Unknown period kind:"):
        code = "cashbox.period.kind_invalid"
    elif "entry has already been dealt with" in message:
        code = "cashbox.late_entry.already_acknowledged"
    else:
        code = "cashbox.request.invalid"
    return cashbox_error(code, detail=message)
