"""The regulation a clinic's clinical record refers to.

A clinical record names the standard it is kept under — on the sheet a
patient fills in and signs, and on the record a clinic hands over. Which
standard that is belongs to the clinic: it is a line of text the clinic
sets, shown as written. The product offers a starting point for the
country the clinic is in and decides nothing beyond that — naming a
standard is a reference, not a statement that the record meets it.

It lives in core because more than one App prints it: the health
questionnaire (Patients) and the record (Clinical record), and the first
must show it with the second switched off.
"""

from __future__ import annotations

from app.core.auth.models import Clinic

SETTINGS_KEY = "record_regulation"
MAX_LENGTH = 300

#: Country (ISO 3166-1 alpha-2) → the standard offered until the clinic
#: writes its own. Only where the product knows the country's standard for
#: the clinical record by its official name.
DEFAULTS: dict[str, str] = {
    "MX": "NOM-004-SSA3-2012, Del expediente clínico",
}

# A clinic that never filled in its address still says where it is by the
# currency it charges in.
_COUNTRY_OF_CURRENCY: dict[str, str] = {"MXN": "MX"}


def default_regulation(clinic: Clinic) -> str | None:
    """The standard offered to this clinic, by the country it is in."""
    country = ((clinic.address or {}).get("country") or "").strip().upper()
    if not country:
        country = _COUNTRY_OF_CURRENCY.get(clinic.currency or "", "")
    return DEFAULTS.get(country)


def record_regulation(clinic: Clinic) -> str | None:
    """The line to print: what the clinic wrote, or the default.

    A clinic that saved an empty line chose to print none, and that is
    kept apart from one that never chose — only the latter gets the
    default.
    """
    stored = (clinic.settings or {}).get(SETTINGS_KEY)
    if stored is None:
        return default_regulation(clinic)
    return stored.strip() or None
