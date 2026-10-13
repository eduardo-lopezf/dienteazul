"""What this module answers when a patient exercises their rights.

The heaviest section of any export: allergies, medication, diseases,
surgical history, and the two people a clinic keeps on file for a patient
— an emergency contact and, for minors, a legal guardian. Those last two
are the only place in the schema where a **third party's** personal data
hangs off a patient record, so they are erased along with the patient
even though the request was never theirs to make.

See ``app.core.privacy.subject`` and ADR 0026.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.core.privacy import SubjectContributor, anonymize_instance

from .models import (
    Allergy,
    AsaAssessment,
    EmergencyContact,
    FamilyHistory,
    HealthQuestionnaire,
    LegalGuardian,
    MedicalContext,
    Medication,
    SurgicalHistory,
    SystemicDisease,
)

_HISTORY_MODELS: tuple[type[DeclarativeBase], ...] = (
    MedicalContext,
    Allergy,
    Medication,
    SystemicDisease,
    SurgicalHistory,
    FamilyHistory,
    HealthQuestionnaire,
    AsaAssessment,
)
_CONTACT_MODELS: tuple[type[DeclarativeBase], ...] = (EmergencyContact, LegalGuardian)


def _row_to_dict(row: DeclarativeBase) -> dict[str, Any]:
    return {
        column.key: getattr(row, column.key)
        for column in row.__table__.columns  # type: ignore[attr-defined]
        if column.key != "clinic_id"
    }


async def _rows_for(
    db: AsyncSession,
    models: tuple[type[DeclarativeBase], ...],
    clinic_id: UUID,
    patient_id: UUID,
) -> list[DeclarativeBase]:
    found: list[DeclarativeBase] = []
    for model in models:
        result = await db.execute(
            select(model).where(
                model.clinic_id == clinic_id,  # type: ignore[attr-defined]
                model.patient_id == patient_id,  # type: ignore[attr-defined]
            )
        )
        found.extend(result.scalars().all())
    return found


def _exporter(models: tuple[type[DeclarativeBase], ...]):
    async def _export(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> list[dict[str, Any]]:
        rows = await _rows_for(db, models, clinic_id, patient_id)
        return [
            {"record_type": row.__tablename__, **_row_to_dict(row)}  # type: ignore[attr-defined]
            for row in rows
        ]

    return _export


def _anonymizer(models: tuple[type[DeclarativeBase], ...]):
    async def _anonymize(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> int:
        rows = await _rows_for(db, models, clinic_id, patient_id)
        return sum(anonymize_instance(row) for row in rows)

    return _anonymize


def get_subject_contributors() -> list[SubjectContributor]:
    return [
        SubjectContributor(
            name="clinical_history",
            export=_exporter(_HISTORY_MODELS),
            anonymize=_anonymizer(_HISTORY_MODELS),
        ),
        SubjectContributor(
            name="contacts",
            export=_exporter(_CONTACT_MODELS),
            anonymize=_anonymizer(_CONTACT_MODELS),
        ),
    ]
