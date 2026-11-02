"""Load stable purchasing error codes from ``errors.json``."""

from __future__ import annotations

from typing import Final

from app.core.errors import AppError, ErrorDefinition, error_raiser, load_error_catalog

ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = load_error_catalog(__file__)

#: Raise one of this module's declared cases. See ``errors.json``.
purchasing_error = error_raiser(ERROR_CATALOG)


def service_error(error: ValueError) -> AppError:
    """Translate purchasing service refusals to stable error codes."""
    message = str(error)
    if message == "Supplier not found":
        code = "purchasing.supplier.not_found"
    elif message == "Order not found":
        code = "purchasing.order.not_found"
    elif message.startswith("Line "):
        code = "purchasing.line.not_found"
    elif "already exists" in message:
        code = "purchasing.supplier.name_taken"
    elif "open orders" in message:
        code = "purchasing.supplier.has_open_orders"
    elif "draft" in message:
        code = "purchasing.order.not_draft"
    elif "cannot receive" in message:
        code = "purchasing.order.not_receivable"
    elif "already closed" in message:
        code = "purchasing.order.already_closed"
    elif "still pending" in message:
        code = "purchasing.receipt.exceeds_pending"
    elif "lot" in message:
        code = "purchasing.receipt.lot_required"
    elif "not in the inventory" in message:
        code = "purchasing.item.unknown"
    else:
        code = "purchasing.request.invalid"
    return purchasing_error(code, detail=message)
