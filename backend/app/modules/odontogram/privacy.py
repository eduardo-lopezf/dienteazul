"""What this module answers when a patient exercises their rights.

Estado dental por pieza, tratamientos aplicados y el histórico del
odontograma. Registro clínico puro: se conserva, y deja de ser
identificativo al anonimizar la ficha de identidad.

See ``app.core.privacy.subject`` and ADR 0026.
"""

from __future__ import annotations

from app.core.privacy import ChildLink, SubjectContributor, patient_keyed_export

from .models import (
    OdontogramHistory,
    OdontogramPreference,
    ToothRecord,
    Treatment,
    TreatmentTooth,
)

CLINICAL_RETENTION = (
    "El historial clínico se conserva: la normativa sanitaria fija un "
    "plazo de conservación que no cede ante una solicitud de supresión. "
    "Los datos dejan de identificar al paciente cuando se anonimiza su "
    "ficha de identidad, no borrando el registro asistencial."
)


def get_subject_contributors() -> list[SubjectContributor]:
    return [
        SubjectContributor(
            name="dental_chart",
            export=patient_keyed_export(ToothRecord),
            retention_reason=CLINICAL_RETENTION,
        ),
        SubjectContributor(
            name="treatments",
            export=patient_keyed_export(Treatment, ChildLink(TreatmentTooth, "treatment_id")),
            retention_reason=CLINICAL_RETENTION,
        ),
        SubjectContributor(
            name="chart_history",
            export=patient_keyed_export(OdontogramHistory),
            retention_reason=CLINICAL_RETENTION,
        ),
        SubjectContributor(
            # Which dentition the chart shows: part of how the chart reads,
            # kept with it.
            name="chart_preferences",
            export=patient_keyed_export(OdontogramPreference),
            retention_reason=CLINICAL_RETENTION,
        ),
    ]
