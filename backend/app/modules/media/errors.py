"""The ways this module refuses, each with a name.

Nine codes for thirty-one raise sites, because the catalogue grows with
*reasons* and the router grows with routes. The five ways a photo's
kind and category can disagree are one reason — the taxonomy refused the
combination — and they share a code; what differs between them is the
sentence, which is already written at each site and is left alone.

Read ``app/core/errors.py`` for what a code is and what travels with it.
"""

from __future__ import annotations

from typing import Final

from fastapi import status

from app.core.errors import AppError

# --- not there ---------------------------------------------------------
DOCUMENT_NOT_FOUND: Final[str] = "media.document.not_found"
ATTACHMENT_NOT_FOUND: Final[str] = "media.attachment.not_found"
PATIENT_NOT_FOUND: Final[str] = "media.patient.not_found"
#: The record a file was to hang off — a plan, a treatment, an appointment.
OWNER_NOT_FOUND: Final[str] = "media.owner.not_found"

# --- there, but not this patient's ------------------------------------
#: Two rows that each exist and do not belong together. A 422 rather than
#: a 404 on purpose: both were found, and saying so is not a leak because
#: the caller already named them both within their own clinic.
WRONG_PATIENT: Final[str] = "media.document.wrong_patient"

# --- the file itself ---------------------------------------------------
FILE_TOO_LARGE: Final[str] = "media.file.too_large"
FILE_TYPE_NOT_ALLOWED: Final[str] = "media.file.type_not_allowed"
DOCUMENT_TYPE_INVALID: Final[str] = "media.document.invalid_type"

#: Kind, category and subtype that do not describe anything real.
PHOTO_TAXONOMY_INVALID: Final[str] = "media.photo.invalid_taxonomy"


def media_error(code: str, *, status_code: int, detail: str) -> AppError:
    """An ``AppError`` with this module's code. Thin on purpose: the
    sentence stays where it was written, next to the check that failed."""
    return AppError(code, status_code=status_code, detail=detail)


def not_found(code: str, detail: str) -> AppError:
    return media_error(code, status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def invalid(code: str, detail: str) -> AppError:
    return media_error(code, status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
