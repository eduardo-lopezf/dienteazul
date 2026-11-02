"""What the inventory links to, and whether each link is live.

Treatments and planned treatments belong to other Apps. The inventory
never imports them: it asks the core for whoever currently supplies each
contract (ADR 0039). No supplier means that App is off, and the
inventory carries on — the materials list keeps the ids it already has,
shows them without names, and no automatic consumption happens because
nothing announces a treatment (ADR 0037).

The direction matters: everything here is the inventory *reading* its
neighbours. Nothing reads the inventory, which is what lets the App be
switched off without touching anything else.
"""

from __future__ import annotations

from app.core.contracts import (
    PatientDirectory,
    PlannedTreatments,
    TreatmentCatalogue,
    provider,
)

CATALOGUE_UNAVAILABLE = "Treatments cannot be listed: the Treatments app is not enabled"
PATIENTS_UNAVAILABLE = "Patients cannot be named: the Patients app is not enabled"


def catalogue() -> TreatmentCatalogue | None:
    return provider(TreatmentCatalogue)


def planned_treatments() -> PlannedTreatments | None:
    return provider(PlannedTreatments)


def patients() -> PatientDirectory | None:
    return provider(PatientDirectory)


def patients_available() -> bool:
    return patients() is not None


def catalogue_available() -> bool:
    return catalogue() is not None
