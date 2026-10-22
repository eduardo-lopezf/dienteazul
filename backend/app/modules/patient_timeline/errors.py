"""The ways this module refuses, each with a name.

The timeline only ever refuses one thing: a patient this clinic does not
have. Read ``app/core/errors.py`` for what a code is and what travels
with it.
"""

from __future__ import annotations

from typing import Final

from app.core.errors import AppError, not_found

PATIENT_NOT_FOUND: Final[str] = "patient_timeline.patient.not_found"


def patient_not_found() -> AppError:
    return not_found(PATIENT_NOT_FOUND, "Patient not found")
