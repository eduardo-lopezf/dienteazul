"""The ways this module refuses, each with a name.

Every refusal here is the same shape — a record of this patient's
clinical file that is not there — so it is one function over the
resource rather than a dozen near-identical constants. The code reads
``patients_clinical.<resource>.not_found``, which is what the catalogue
would have spelled out anyway.

Read ``app/core/errors.py`` for what a code is and what travels with it.
"""

from __future__ import annotations

from fastapi import status

from app.core.errors import AppError, not_found

#: Spelled here so a reader sees the shape without running it.
CODE_TEMPLATE = "patients_clinical.{resource}.not_found"


def record_not_found(resource: str, label: str) -> AppError:
    """``resource`` names the code; ``label`` is what the person reads.

    Both are given rather than derived from one another: the code is a
    contract and must not move when the wording is improved, and the
    wording is a sentence that should not be forced to match a key.
    """
    return not_found(CODE_TEMPLATE.format(resource=resource), f"{label} not found")


def rejected(resource: str, reason: str) -> AppError:
    """A rule of this module's own refused the write.

    The service raises ``ValueError`` with the sentence to show — a
    questionnaire with neither signature nor scan, an ASA class that is
    not offered. The code says which record refused; the reason is the
    service's own words and stays unaltered.
    """
    return AppError(
        f"patients_clinical.{resource}.rejected",
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=reason,
    )
