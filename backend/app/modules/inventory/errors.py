"""Load stable inventory error codes from ``errors.json``."""

from __future__ import annotations

from typing import Final

from app.core.errors import AppError, ErrorDefinition, error_raiser, load_error_catalog

ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = load_error_catalog(__file__)

#: Raise one of this module's declared cases. See ``errors.json``.
inventory_error = error_raiser(ERROR_CATALOG)


def service_error(error: ValueError) -> AppError:
    """Translate inventory service refusals to stable error codes."""
    message = str(error)
    if message == "Article not found":
        code = "inventory.item.not_found"
    elif message == "Location not found":
        code = "inventory.location.not_found"
    elif message.startswith("Lot not found"):
        code = "inventory.lot.not_found"
    elif "already exists" in message and message.startswith("An article"):
        code = "inventory.item.code_taken"
    elif message.startswith("A location named"):
        code = "inventory.location.name_taken"
    elif message.startswith("Lot '"):
        code = "inventory.lot.code_taken"
    elif "name the lot" in message:
        code = "inventory.lot.required"
    elif "must track lots" in message:
        code = "inventory.implant.not_traceable"
    elif "does not track lots" in message:
        code = "inventory.lot.not_tracked"
    elif message.startswith("Not enough stock"):
        code = "inventory.stock.insufficient"
    elif "changes nothing" in message:
        code = "inventory.movement.zero"
    elif "needs a positive quantity" in message:
        code = "inventory.movement.sign_invalid"
    elif "location is archived" in message:
        code = "inventory.location.archived"
    elif "still holds stock" in message:
        code = "inventory.location.not_empty"
    elif "two different locations" in message:
        code = "inventory.transfer.same_location"
    else:
        code = "inventory.request.invalid"
    return inventory_error(code, detail=message)
