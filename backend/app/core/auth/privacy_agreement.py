"""The privacy agreement a clinic's holder accepts, and whether the one
they accepted is still the current one.

The text lives in the frontend's locale files
(``onboarding.privacy.sections``); its version is named here and in
``frontend/app/config/privacyAgreement.ts``, and the two change together
whenever the text does (``frontend/tests/privacy-agreement.test.ts`` fails
when they differ). A clinic that accepted another version — or accepted
before versions were kept — is asked again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Clinic

#: The date the text last changed, and a letter after it for a second
#: change that day.
PRIVACY_AGREEMENT_VERSION = "2026-10-12"


def needs_renewal(clinic: Clinic) -> bool:
    """The clinic accepted the agreement, and not the one in force. A
    clinic that was never asked is not asked now."""
    return (
        clinic.privacy_accepted_at is not None
        and clinic.privacy_accepted_version != PRIVACY_AGREEMENT_VERSION
    )
