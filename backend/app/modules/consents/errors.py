"""Load stable consent error codes from ``errors.json``."""

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
consents_error = error_raiser(ERROR_CATALOG)


def consent_domain_error(message: str, *, state_error: bool = False) -> AppError:
    if state_error:
        code = "consents.consent.invalid_state"
    elif message.startswith("Professionals are not available"):
        code = "consents.professionals.unavailable"
    elif message == "Professional not found in this clinic":
        code = "consents.professional.not_found"
    elif message == "Patient not found in this clinic":
        code = "consents.patient.not_found"
    elif message == "Template not found for this kind of consent":
        code = "consents.template.invalid_for_kind"
    elif message == "A consent needs a title and a text":
        code = "consents.consent.content_required"
    elif message == "An informed consent must name the professional who explained it":
        code = "consents.consent.professional_required"
    elif message == "Documents are not available — a scan cannot be filed":
        code = "consents.documents.unavailable"
    elif message == "The scanned document is not one of this patient's files":
        code = "consents.scan.not_found"
    else:
        code = "consents.consent.invalid_state" if state_error else "consents.consent.invalid"
    return consents_error(code, detail=message)
