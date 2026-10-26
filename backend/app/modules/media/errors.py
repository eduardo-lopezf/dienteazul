"""Load stable media error codes from ``errors.json``."""

from __future__ import annotations

from typing import Final

from fastapi import status

from app.core.errors import AppError, ErrorDefinition, error_raiser, load_error_catalog

ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = load_error_catalog(__file__)

_raise_for = error_raiser(ERROR_CATALOG)

# Named codes, so a route reads ``not_found(DOCUMENT_NOT_FOUND, ...)``
# rather than a dotted string. Media is the only module that does this.
DOCUMENT_NOT_FOUND: Final[str] = "media.document.not_found"
ATTACHMENT_NOT_FOUND: Final[str] = "media.attachment.not_found"
PATIENT_NOT_FOUND: Final[str] = "media.patient.not_found"
OWNER_NOT_FOUND: Final[str] = "media.owner.not_found"
WRONG_PATIENT: Final[str] = "media.document.wrong_patient"
FILE_TOO_LARGE: Final[str] = "media.file.too_large"
FILE_TYPE_NOT_ALLOWED: Final[str] = "media.file.type_not_allowed"
DOCUMENT_TYPE_INVALID: Final[str] = "media.document.invalid_type"
PHOTO_TAXONOMY_INVALID: Final[str] = "media.photo.invalid_taxonomy"
DOCUMENT_SELF_PAIR: Final[str] = "media.document.self_pair"
ATTACHMENT_OWNER_TYPE_INVALID: Final[str] = "media.attachment.owner_type_invalid"


def media_error(code: str, *, status_code: int, detail: str) -> AppError:
    """Raise a declared case, with the caller stating the status it expects.

    Unlike every other module's raiser this one takes ``status_code``
    and refuses when it disagrees with the catalogue. It is a guard
    against the two drifting while ``not_found`` and ``invalid`` below
    hard-code one: the helper's name would keep promising a 404 after
    the catalogue had moved the case to a 409.
    """
    definition = ERROR_CATALOG[code]
    if status_code != definition.status_code:
        raise ValueError(f"status mismatch for {code}: {status_code} != {definition.status_code}")
    return _raise_for(code, detail=detail)


def not_found(code: str, detail: str) -> AppError:
    return media_error(code, status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def invalid(code: str, detail: str) -> AppError:
    return media_error(code, status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
