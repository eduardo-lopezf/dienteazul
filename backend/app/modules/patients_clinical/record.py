"""What this module contributes to a clinical record.

The antecedents: allergies, medications, systemic diseases and surgical
history. Four sections rather than one, because that is how they are read —
a colleague scanning for a drug allergy is not reading the surgical history —
and because an export maps a section to a CDA/FHIR section, not a module.

Every entry carries what ADR 0032 made it carry: clinical time, the lifecycle
state, and the professional responsible. None of that is computed here; the
composition reads what the rows already say.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.record import EntryStatus, RecordEntry, RecordSection, SectionCategory

from .models import (
    Allergy,
    AsaAssessment,
    FamilyHistory,
    HealthQuestionnaire,
    MedicalContext,
    Medication,
    SurgicalHistory,
    SystemicDisease,
)


def _status(row) -> EntryStatus:
    """The three states ADR 0032 keeps apart, read off the row.

    Retracted wins over ended: an entry that should never have existed is not
    "a fact that stopped being true", and a reader has to be able to tell.
    """
    if row.retracted_at is not None:
        return EntryStatus.RETRACTED
    if row.ended_at is not None:
        return EntryStatus.ENDED
    return EntryStatus.ACTIVE


def _occurred_at(row, clinical_date=None) -> datetime:
    """Clinical time where the row knows it, creation time otherwise.

    A surgery dated 2019 belongs in 2019 even if it was typed in today; an
    allergy has no onset date in this schema, so the day it was recorded is
    the best the record can honestly claim.
    """
    if clinical_date is not None:
        return datetime.combine(clinical_date, datetime.min.time(), tzinfo=UTC)
    return row.created_at


def _attribution(row) -> dict:
    return {
        "authored_by_professional_id": row.recorded_by_professional_id,
        "recorded_by_user_id": row.recorded_by_user_id,
    }


async def _rows(db: AsyncSession, model, clinic_id: UUID, patient_id: UUID) -> list:
    """Every row, retracted ones included — the composition filters.

    A section that silently dropped them could not answer "what did the chart
    say that day", which is the question the whole append-only rule exists for.
    """
    result = await db.execute(
        select(model).where(
            model.clinic_id == clinic_id,
            model.patient_id == patient_id,
        )
    )
    return list(result.scalars())


async def _collect_allergies(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> list[RecordEntry]:
    return [
        RecordEntry(
            occurred_at=_occurred_at(row),
            summary=row.name,
            detail={
                "name": row.name,
                "type": row.type,
                "severity": row.severity,
                "reaction": row.reaction,
                "notes": row.notes,
            },
            status=_status(row),
            source_table="patients_clinical_allergy",
            source_id=row.id,
            **_attribution(row),
        )
        for row in await _rows(db, Allergy, clinic_id, patient_id)
    ]


async def _collect_medications(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> list[RecordEntry]:
    return [
        RecordEntry(
            occurred_at=_occurred_at(row, row.start_date),
            summary=row.name,
            detail={
                "name": row.name,
                "dosage": row.dosage,
                "frequency": row.frequency,
                "start_date": row.start_date,
                "notes": row.notes,
            },
            status=_status(row),
            source_table="patients_clinical_medication",
            source_id=row.id,
            **_attribution(row),
        )
        for row in await _rows(db, Medication, clinic_id, patient_id)
    ]


async def _collect_diseases(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> list[RecordEntry]:
    return [
        RecordEntry(
            occurred_at=_occurred_at(row, row.diagnosis_date),
            summary=row.name,
            detail={
                "name": row.name,
                "type": row.type,
                "diagnosis_date": row.diagnosis_date,
                "is_controlled": row.is_controlled,
                "is_critical": row.is_critical,
                "medications": row.medications,
                "notes": row.notes,
            },
            status=_status(row),
            source_table="patients_clinical_systemic_disease",
            source_id=row.id,
            **_attribution(row),
        )
        for row in await _rows(db, SystemicDisease, clinic_id, patient_id)
    ]


async def _collect_surgeries(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> list[RecordEntry]:
    return [
        RecordEntry(
            occurred_at=_occurred_at(row, row.surgery_date),
            summary=row.procedure,
            detail={
                "procedure": row.procedure,
                "surgery_date": row.surgery_date,
                "complications": row.complications,
                "notes": row.notes,
            },
            status=_status(row),
            source_table="patients_clinical_surgical_history",
            source_id=row.id,
            **_attribution(row),
        )
        for row in await _rows(db, SurgicalHistory, clinic_id, patient_id)
    ]


async def _collect_family(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> list[RecordEntry]:
    return [
        RecordEntry(
            occurred_at=_occurred_at(row),
            summary=row.condition,
            detail={"condition": row.condition, "relative": row.relative, "notes": row.notes},
            status=_status(row),
            source_table="patients_clinical_family_history",
            source_id=row.id,
            **_attribution(row),
        )
        for row in await _rows(db, FamilyHistory, clinic_id, patient_id)
    ]


async def _collect_questionnaires(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> list[RecordEntry]:
    """What the patient declared at each visit, as they declared it."""
    return [
        RecordEntry(
            occurred_at=row.taken_at,
            summary=row.chief_complaint or "",
            detail={
                # Only said for the pediatric form: the adult one is the default.
                "form_kind": row.form_kind if row.form_kind != "adult" else None,
                "chief_complaint": row.chief_complaint,
                # What the pediatric form asks to write (school, guardian, weight…).
                "form_data": [
                    {"field": key, "value": value} for key, value in (row.form_data or {}).items()
                ]
                or None,
                "blood_type": row.blood_type,
                "declared_allergies": row.declared_allergies,
                # Only what was answered "yes": that is what a reader scans for.
                "affirmative_answers": [
                    {"question": key, "detail": answer.get("detail")}
                    for key, answer in (row.answers or {}).items()
                    if answer.get("answer")
                ],
                "declared_conditions": row.conditions,
                "drugs_detail": row.drugs_detail,
                "other_conditions": row.other_conditions,
                "scan_document_id": row.scan_document_id,
                "on_paper": True if row.scan_document_id else None,
                "signed_by_name": row.signed_by_name,
                "signer_capacity": row.signer_capacity,
                "signed_at": row.signed_at,
            },
            status=_status(row),
            source_table="patients_clinical_health_questionnaire",
            source_id=row.id,
            **_attribution(row),
        )
        for row in await _rows(db, HealthQuestionnaire, clinic_id, patient_id)
    ]


async def _collect_asa(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> list[RecordEntry]:
    """Every assessment, on the day it was made: the current class and the
    ones it superseded."""
    return [
        RecordEntry(
            occurred_at=row.assessed_at,
            summary=f"ASA {row.label}",
            detail={"asa_class": f"ASA {row.label}", "rationale": row.rationale},
            status=_status(row),
            source_table="patients_clinical_asa_assessment",
            source_id=row.id,
            **_attribution(row),
        )
        for row in await _rows(db, AsaAssessment, clinic_id, patient_id)
    ]


_CONTEXT_FIELDS = (
    "is_pregnant",
    "pregnancy_week",
    "is_lactating",
    "is_on_anticoagulants",
    "anticoagulant_medication",
    "inr_value",
    "last_inr_date",
    "is_smoker",
    "smoking_frequency",
    "alcohol_consumption",
    "bruxism",
    "adverse_reactions_to_anesthesia",
    "anesthesia_reaction_details",
)


async def _collect_context(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> list[RecordEntry]:
    """Pregnancy, anticoagulants, habits and reactions to anaesthesia.

    One row per patient, overwritten in place: the record can say what it
    holds today and when it was last touched, not what it said before.
    """
    row = (
        await db.execute(
            select(MedicalContext).where(
                MedicalContext.clinic_id == clinic_id,
                MedicalContext.patient_id == patient_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return []
    return [
        RecordEntry(
            occurred_at=row.last_updated_at or row.updated_at or row.created_at,
            summary="",
            detail={name: getattr(row, name) for name in _CONTEXT_FIELDS},
            recorded_by_user_id=row.last_updated_by,
            source_table="patients_clinical_medical_context",
            source_id=row.patient_id,
        )
    ]


def get_record_sections() -> list[RecordSection]:
    return [
        RecordSection(
            name="health_questionnaires",
            title_key="record.section.health_questionnaires",
            category=SectionCategory.ANTECEDENTS,
            collect=_collect_questionnaires,
            order=1,
        ),
        RecordSection(
            name="asa_assessments",
            title_key="record.section.asa_assessments",
            category=SectionCategory.ANTECEDENTS,
            collect=_collect_asa,
            order=2,
        ),
        RecordSection(
            name="family_history",
            title_key="record.section.family_history",
            category=SectionCategory.ANTECEDENTS,
            collect=_collect_family,
            order=3,
        ),
        RecordSection(
            name="medical_context",
            title_key="record.section.medical_context",
            category=SectionCategory.ANTECEDENTS,
            collect=_collect_context,
            order=5,
        ),
        RecordSection(
            name="allergies",
            title_key="record.section.allergies",
            category=SectionCategory.ANTECEDENTS,
            collect=_collect_allergies,
            order=10,
        ),
        RecordSection(
            name="medications",
            title_key="record.section.medications",
            category=SectionCategory.ANTECEDENTS,
            collect=_collect_medications,
            order=20,
        ),
        RecordSection(
            name="systemic_diseases",
            title_key="record.section.systemic_diseases",
            category=SectionCategory.ANTECEDENTS,
            collect=_collect_diseases,
            order=30,
        ),
        RecordSection(
            name="surgical_history",
            title_key="record.section.surgical_history",
            category=SectionCategory.ANTECEDENTS,
            collect=_collect_surgeries,
            order=40,
        ),
    ]
