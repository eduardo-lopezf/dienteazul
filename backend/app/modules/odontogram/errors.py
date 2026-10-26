"""Load stable odontogram error codes from ``errors.json``."""

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
odontogram_error = error_raiser(ERROR_CATALOG)


def treatment_service_error(error: ValueError) -> AppError:
    """Map known treatment-domain refusals while preserving their details."""
    message = str(error)
    if message == "Catalog item not found":
        code = "odontogram.treatment.catalog_item_not_found"
    elif message.startswith("clinical_type=") and "conflicts with catalog mapping" in message:
        code = "odontogram.treatment.catalog_mapping_conflict"
    elif message == "clinical_type is required when no catalog item is given":
        code = "odontogram.treatment.clinical_type_required"
    elif message == "bridge requires at least one pillar tooth":
        code = "odontogram.treatment.bridge_requires_pillar"
    elif "is for " in message and " teeth only; not on tooth " in message:
        code = "odontogram.treatment.dentition_mismatch"
    elif message.startswith("clinical_type=") and "requires at least 2 teeth" in message:
        code = "odontogram.treatment.atomic_tooth_count_invalid"
    else:
        code = "odontogram.treatment.invalid"
    return odontogram_error(code, detail=message)
