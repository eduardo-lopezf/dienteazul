"""What the Budgets and payments App links to, and whether each link is live.

Patients, the treatment catalog, the odontogram and the professionals
directory belong to other Apps the deployment can switch off. They are
``integrates`` of this App's modules, not ``depends`` (ADR 0037): while
one is off the App keeps running, offers none of its records, writes
nothing to it and deletes nothing. Stored links stay in the database and
show again when the App returns.

- Patients off: existing budgets, invoices and payments can be read,
  without the patient; nothing new that needs a patient is created.
- Catalog off: no line is added to a budget or an invoice; existing
  ones are read and collected.
- Professionals off: no professional is assigned; stored ones are hidden.

``payments`` and ``billing`` depend on ``budget`` and use these too.
"""

from __future__ import annotations

from app.core.plugins.registry import module_registry

PATIENTS_UNAVAILABLE = "The Patients app is not enabled: nothing new can be made for a patient"
CATALOG_UNAVAILABLE = "The treatment catalog is not enabled: lines cannot be added"
PROFESSIONALS_UNAVAILABLE = "Professionals cannot be assigned: the Professionals app is not enabled"


class AppUnavailableError(ValueError):
    """An integrated App this action needs is off.

    A ``ValueError``, so it answers 400 wherever one already does — as
    the agenda's refusals do.
    """


def patients_available() -> bool:
    return module_registry.is_installed("patients")


def catalog_available() -> bool:
    return module_registry.is_installed("catalog")


def professionals_available() -> bool:
    return module_registry.is_installed("professionals")


def odontogram_available() -> bool:
    return module_registry.is_installed("odontogram")


def require_patients() -> None:
    if not patients_available():
        raise AppUnavailableError(PATIENTS_UNAVAILABLE)


def require_catalog() -> None:
    if not catalog_available():
        raise AppUnavailableError(CATALOG_UNAVAILABLE)


def require_professionals() -> None:
    if not professionals_available():
        raise AppUnavailableError(PROFESSIONALS_UNAVAILABLE)
