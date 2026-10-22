"""The ways this module refuses, each with a name.

One code per *case*, not per raise site: the five routes that cannot find
a patient are one case seen from five places, and giving each its own
code would make the catalogue grow with the router rather than with the
reasons. Where two codes would carry the same meaning, there is one.

Read ``app/core/errors.py`` for what a code is and what travels with it.
"""

from __future__ import annotations

from typing import Final

from app.core.errors import AppError, not_found

#: Asked for a patient this clinic does not have. Covers "never existed"
#: and "belongs to another clinic" on purpose: telling those apart would
#: answer whether an id exists elsewhere, which is not the caller's to
#: know (multi-tenancy, `CLAUDE.md`).
PATIENT_NOT_FOUND: Final[str] = "patients.patient.not_found"


def patient_not_found() -> AppError:
    return not_found(PATIENT_NOT_FOUND, "Patient not found")
