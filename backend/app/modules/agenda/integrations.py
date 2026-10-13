"""What the agenda links to, and whether each link is live.

Patients, professionals, planned treatments and working hours belong to
other Apps. The agenda never imports them: it asks the core for whoever
currently supplies each contract (ADR 0039). No supplier means the App
is off, and the agenda books without that link: it accepts no new one,
shows none of those already stored, and deletes nothing — they show
again when the App returns (ADR 0037).
"""

from __future__ import annotations

from app.core.contracts import (
    PatientDirectory,
    PlanConsents,
    PlannedTreatments,
    ProfessionalDirectory,
    WorkingHours,
    provider,
)

PATIENTS_UNAVAILABLE = "Patients cannot be assigned: the Patients app is not enabled"
PROFESSIONALS_UNAVAILABLE = "Professionals cannot be assigned: the Professionals app is not enabled"
TREATMENTS_UNAVAILABLE = "Treatments cannot be assigned: the Treatments app is not enabled"


def patients() -> PatientDirectory | None:
    return provider(PatientDirectory)


def professionals() -> ProfessionalDirectory | None:
    return provider(ProfessionalDirectory)


def planned_treatments() -> PlannedTreatments | None:
    return provider(PlannedTreatments)


def working_hours() -> WorkingHours | None:
    return provider(WorkingHours)


def plan_consents() -> PlanConsents | None:
    return provider(PlanConsents)


def patients_available() -> bool:
    return patients() is not None


def professionals_available() -> bool:
    return professionals() is not None


def treatments_available() -> bool:
    return planned_treatments() is not None
