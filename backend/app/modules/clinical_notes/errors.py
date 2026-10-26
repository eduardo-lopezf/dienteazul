"""Load stable clinical-notes error codes from ``errors.json``."""

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
clinical_notes_error = error_raiser(ERROR_CATALOG)


def owner_error(message: str) -> AppError:
    if message.startswith("Appointments are not available"):
        code = "clinical_notes.owner.unavailable"
    elif "has no patient" in message:
        code = "clinical_notes.owner.patient_required"
    elif message.startswith("documents not found:"):
        code = "clinical_notes.attachment.documents_not_found"
    elif "not found" in message:
        code = "clinical_notes.owner.not_found"
    else:
        code = "clinical_notes.owner.invalid"
    return clinical_notes_error(code, detail=message)
