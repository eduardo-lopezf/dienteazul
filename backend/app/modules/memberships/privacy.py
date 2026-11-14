"""What this module answers when a patient exercises their rights.

Membresías, sus cuotas y los servicios incluidos usados. Las cuotas son
cobros: se conservan como documentos contables.

See ``app.core.privacy.subject`` and ADR 0026.
"""

from __future__ import annotations

from app.core.privacy import ChildLink, SubjectContributor, patient_keyed_export

from .models import MembershipBenefitUsage, MembershipPeriod, PatientMembership

FISCAL_RETENTION = (
    "Las cuotas de membresía son cobros: su conservación la fija la normativa "
    "tributaria, que no cede ante una solicitud de supresión."
)


def get_subject_contributors() -> list[SubjectContributor]:
    return [
        SubjectContributor(
            name="memberships",
            export=patient_keyed_export(
                PatientMembership,
                ChildLink(MembershipPeriod, "membership_id"),
                ChildLink(MembershipBenefitUsage, "membership_id"),
            ),
            retention_reason=FISCAL_RETENTION,
        ),
    ]
