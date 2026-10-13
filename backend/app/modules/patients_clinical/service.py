"""Service layer for patients_clinical.

Wraps CRUD for the seven tables plus two derived helpers:
* :meth:`PatientsClinicalService.build_medical_history` — aggregates
  medical_context + allergies + meds + diseases + surgeries into the
  legacy JSONB-shaped response for the form.
* :meth:`PatientsClinicalService.compute_alerts` — the former
  ``Patient.active_alerts`` property, moved here because alerts are
  now derived from normalized rows instead of a blob.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.contracts import PatientDocuments, ProfessionalDirectory, provider
from app.core.regulation import record_regulation

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
from .questionnaire import CONDITION_GROUPS, CONDITIONS, FORM_VERSION, QUESTIONS

#: The four history tables that are append-only per ADR 0032. Emergency
#: contacts and legal guardians are 1:1 rows keyed by ``patient_id`` and are
#: not in this set — making them append-only means re-keying them.
_HISTORY_ENTRY_MODELS = (Allergy, Medication, SystemicDisease, SurgicalHistory, FamilyHistory)

#: Written into ``retraction_reason`` when a line disappears from the medical
#: history form. The form has no field for "when did this stop being true", so
#: removing a line cannot be read as an end date — it is the user taking the
#: entry back, which is a retraction, and it says so rather than pretending to
#: know more.
REMOVED_FROM_FORM = "removed_from_history_form"


def _live(model):
    """Rows a form shows by default: still true, never retracted."""
    return (model.retracted_at.is_(None)) & (model.ended_at.is_(None))


async def _attribution(db: AsyncSession, clinic_id: UUID, user_id: UUID | None) -> dict:
    """Who to credit for a clinical entry: the account, and the professional.

    Two fields, because an assistant may type what a dentist is responsible
    for (ADR 0032). The professional is the acting account's directory profile
    — `professionals.user_id`, which an admin states rather than the product
    inferring it from a matching email.

    An account with no profile yields None, and that is the answer, not a gap:
    a guess written into a document meant to be evidence is worse than a blank.

    The directory is reached through its core contract, not imported
    (ADR 0039). With the Professionals App off there is no directory to ask
    and the entry names no professional — the same truthful blank.
    """
    directory = provider(ProfessionalDirectory)
    return {
        "recorded_by_user_id": user_id,
        "recorded_by_professional_id": (
            await directory.for_account(db, clinic_id, user_id) if directory else None
        ),
    }


class PatientsClinicalService:
    """Static service: all methods take ``db`` + ``clinic_id`` explicitly."""

    # --- Medical context (1:1) -----------------------------------------

    @staticmethod
    async def get_medical_context(db: AsyncSession, patient_id: UUID) -> MedicalContext | None:
        result = await db.execute(
            select(MedicalContext).where(MedicalContext.patient_id == patient_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert_medical_context(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        data: dict[str, Any],
        user_id: UUID | None,
    ) -> MedicalContext:
        existing = await PatientsClinicalService.get_medical_context(db, patient_id)
        now = datetime.now(UTC)

        if existing is None:
            existing = MedicalContext(
                patient_id=patient_id,
                clinic_id=clinic_id,
                **data,
                last_updated_at=now,
                last_updated_by=user_id,
            )
            db.add(existing)
        else:
            for key, value in data.items():
                setattr(existing, key, value)
            existing.last_updated_at = now
            existing.last_updated_by = user_id

        await db.flush()
        return existing

    @staticmethod
    async def retract_entry(
        db: AsyncSession,
        entry,
        reason: str | None = None,
        user_id: UUID | None = None,
    ) -> None:
        """Take a clinical entry back without destroying it.

        Used where the API said "delete". The row survives, stops driving
        alerts and stops appearing in what leaves the clinic; what it said,
        and that it was taken back, stay answerable — which is the property
        that turns stored data into a record (ADR 0032).

        Already-retracted entries are left alone rather than re-stamped: the
        first retraction is the one that happened.
        """
        if entry.retracted_at is not None:
            return
        entry.retracted_at = datetime.now(UTC)
        entry.retraction_reason = reason
        if user_id is not None and entry.recorded_by_user_id is None:
            entry.recorded_by_user_id = user_id
        await db.flush()

    # --- Allergy -------------------------------------------------------

    @staticmethod
    async def list_allergies(
        db: AsyncSession, patient_id: UUID, include_history: bool = False
    ) -> list[Allergy]:
        """Live allergies, or everything ever recorded when asked.

        The default is what a form and an alert need: currently true, never
        retracted. `include_history` is how the clinical record reaches the
        rest — a discontinued entry is part of the history, and a retracted one
        still has to be answerable ("what did the chart say that day").
        """
        query = select(Allergy).where(Allergy.patient_id == patient_id)
        if not include_history:
            query = query.where(_live(Allergy))
        result = await db.execute(query.order_by(Allergy.created_at))
        return list(result.scalars())

    @staticmethod
    async def create_allergy(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        data: dict,
        user_id: UUID | None = None,
    ) -> Allergy:
        allergy = Allergy(
            clinic_id=clinic_id,
            patient_id=patient_id,
            **await _attribution(db, clinic_id, user_id),
            **data,
        )
        db.add(allergy)
        await db.flush()
        return allergy

    @staticmethod
    async def get_allergy(db: AsyncSession, allergy_id: UUID) -> Allergy | None:
        result = await db.execute(select(Allergy).where(Allergy.id == allergy_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def update_allergy(db: AsyncSession, allergy: Allergy, data: dict) -> Allergy:
        for k, v in data.items():
            setattr(allergy, k, v)
        await db.flush()
        return allergy

    @staticmethod
    async def delete_allergy(
        db: AsyncSession, allergy: Allergy, user_id: UUID | None = None
    ) -> None:
        """Retract, never delete — see :meth:`retract_entry`.

        The name stays `delete_*` because that is what the endpoint is called
        and what the caller means; what it does to the row is the thing that
        changed.
        """
        await PatientsClinicalService.retract_entry(db, allergy, user_id=user_id)

    # --- Medication ----------------------------------------------------

    @staticmethod
    async def list_medications(
        db: AsyncSession, patient_id: UUID, include_history: bool = False
    ) -> list[Medication]:
        query = select(Medication).where(Medication.patient_id == patient_id)
        if not include_history:
            query = query.where(_live(Medication))
        result = await db.execute(query.order_by(Medication.created_at))
        return list(result.scalars())

    @staticmethod
    async def create_medication(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        data: dict,
        user_id: UUID | None = None,
    ) -> Medication:
        med = Medication(
            clinic_id=clinic_id,
            patient_id=patient_id,
            **await _attribution(db, clinic_id, user_id),
            **data,
        )
        db.add(med)
        await db.flush()
        return med

    @staticmethod
    async def get_medication(db: AsyncSession, medication_id: UUID) -> Medication | None:
        result = await db.execute(select(Medication).where(Medication.id == medication_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def update_medication(db: AsyncSession, med: Medication, data: dict) -> Medication:
        for k, v in data.items():
            setattr(med, k, v)
        await db.flush()
        return med

    @staticmethod
    async def delete_medication(
        db: AsyncSession, med: Medication, user_id: UUID | None = None
    ) -> None:
        await PatientsClinicalService.retract_entry(db, med, user_id=user_id)

    # --- Systemic disease ----------------------------------------------

    @staticmethod
    async def list_systemic_diseases(
        db: AsyncSession, patient_id: UUID, include_history: bool = False
    ) -> list[SystemicDisease]:
        query = select(SystemicDisease).where(SystemicDisease.patient_id == patient_id)
        if not include_history:
            query = query.where(_live(SystemicDisease))
        result = await db.execute(query.order_by(SystemicDisease.created_at))
        return list(result.scalars())

    @staticmethod
    async def create_systemic_disease(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        data: dict,
        user_id: UUID | None = None,
    ) -> SystemicDisease:
        disease = SystemicDisease(
            clinic_id=clinic_id,
            patient_id=patient_id,
            **await _attribution(db, clinic_id, user_id),
            **data,
        )
        db.add(disease)
        await db.flush()
        return disease

    @staticmethod
    async def get_systemic_disease(db: AsyncSession, disease_id: UUID) -> SystemicDisease | None:
        result = await db.execute(select(SystemicDisease).where(SystemicDisease.id == disease_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def update_systemic_disease(
        db: AsyncSession, disease: SystemicDisease, data: dict
    ) -> SystemicDisease:
        for k, v in data.items():
            setattr(disease, k, v)
        await db.flush()
        return disease

    @staticmethod
    async def delete_systemic_disease(
        db: AsyncSession, disease: SystemicDisease, user_id: UUID | None = None
    ) -> None:
        await PatientsClinicalService.retract_entry(db, disease, user_id=user_id)

    # --- Health questionnaire -------------------------------------------

    @staticmethod
    async def list_questionnaires(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> list[HealthQuestionnaire]:
        """Newest first, retracted ones left out."""
        result = await db.execute(
            select(HealthQuestionnaire)
            .where(
                HealthQuestionnaire.clinic_id == clinic_id,
                HealthQuestionnaire.patient_id == patient_id,
                _live(HealthQuestionnaire),
            )
            .order_by(HealthQuestionnaire.taken_at.desc())
        )
        return list(result.scalars())

    @staticmethod
    async def get_questionnaire(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID, questionnaire_id: UUID
    ) -> HealthQuestionnaire | None:
        result = await db.execute(
            select(HealthQuestionnaire).where(
                HealthQuestionnaire.id == questionnaire_id,
                HealthQuestionnaire.clinic_id == clinic_id,
                HealthQuestionnaire.patient_id == patient_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_questionnaire(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID, data: dict, user_id: UUID | None
    ) -> HealthQuestionnaire:
        """Record what the patient declared. It is never edited afterwards.

        Raises ``ValueError`` for an answer to a question the form does not
        ask, a condition it does not list, an empty questionnaire, a scan
        that is not one of this patient's documents, or one that carries
        neither the patient's signature nor the scan of the signed sheet.
        """
        unknown = sorted(set(data["answers"]) - set(QUESTIONS)) + sorted(
            set(data["conditions"]) - CONDITIONS
        )
        if unknown:
            raise ValueError(f"Not part of the questionnaire: {', '.join(unknown)}")

        scan = data.get("scan_document_id")
        if scan is not None:
            documents = provider(PatientDocuments)
            if documents is None or not await documents.belongs_to(db, clinic_id, patient_id, scan):
                raise ValueError("The scan is not one of this patient's documents")
        elif not (data["answers"] or data["conditions"] or data.get("chief_complaint")):
            raise ValueError("An empty questionnaire says nothing")

        signature = data.get("signature")
        if signature is not None and scan is not None:
            # The sheet was signed by hand; a second signature would say
            # the patient signed something they never saw on screen.
            raise ValueError("A questionnaire filled in on paper is signed on the sheet")
        if signature is None and scan is None:
            # Either is valid; neither is not. What a patient declares is
            # theirs once they sign it — on screen, or on the sheet.
            raise ValueError(
                "A questionnaire is signed by the patient on screen, or filed as the signed sheet"
            )

        now = datetime.now(UTC)
        clinic = await db.get(Clinic, clinic_id)

        questionnaire = HealthQuestionnaire(
            clinic_id=clinic_id,
            patient_id=patient_id,
            taken_at=data.get("taken_at") or now,
            signed_at=now if signature else None,
            signed_by_name=signature["signed_by_name"].strip() if signature else None,
            signer_capacity=signature["signer_capacity"] if signature else None,
            signature_data={"png": signature["png"]} if signature else None,
            # What the form named today, kept with what was declared under it.
            regulation=record_regulation(clinic) if clinic is not None else None,
            form_version=FORM_VERSION,
            chief_complaint=data.get("chief_complaint") or None,
            blood_type=data.get("blood_type") or None,
            declared_allergies=data.get("declared_allergies") or None,
            answers=data["answers"],
            # In the form's own order, whatever order they were ticked in.
            conditions=[
                key
                for group in CONDITION_GROUPS.values()
                for key in group
                if key in set(data["conditions"])
            ],
            drugs_detail=data.get("drugs_detail") or None,
            other_conditions=data.get("other_conditions") or None,
            scan_document_id=scan,
            **await _attribution(db, clinic_id, user_id),
        )
        db.add(questionnaire)
        await db.flush()
        return questionnaire

    # --- ASA physical status --------------------------------------------

    @staticmethod
    async def list_asa_assessments(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> list[AsaAssessment]:
        """Newest first, retracted ones left out. The first is the current class."""
        result = await db.execute(
            select(AsaAssessment)
            .where(
                AsaAssessment.clinic_id == clinic_id,
                AsaAssessment.patient_id == patient_id,
                AsaAssessment.retracted_at.is_(None),
            )
            .order_by(AsaAssessment.assessed_at.desc(), AsaAssessment.created_at.desc())
        )
        return list(result.scalars())

    @staticmethod
    async def get_asa_assessment(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID, assessment_id: UUID
    ) -> AsaAssessment | None:
        result = await db.execute(
            select(AsaAssessment).where(
                AsaAssessment.id == assessment_id,
                AsaAssessment.clinic_id == clinic_id,
                AsaAssessment.patient_id == patient_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_asa_assessment(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID, data: dict, user_id: UUID | None
    ) -> AsaAssessment:
        """Append an assessment. The previous ones stay as they were.

        Raises ``ValueError`` for one dated in the future: a judgement is
        made on a day that has happened.
        """
        now = datetime.now(UTC)
        assessed_at = data.get("assessed_at") or now
        if assessed_at > now:
            raise ValueError("An assessment cannot be dated in the future")
        assessment = AsaAssessment(
            clinic_id=clinic_id,
            patient_id=patient_id,
            assessed_at=assessed_at,
            asa_class=data["asa_class"],
            is_emergency=data.get("is_emergency", False),
            rationale=(data.get("rationale") or "").strip() or None,
            **await _attribution(db, clinic_id, user_id),
        )
        db.add(assessment)
        await db.flush()
        return assessment

    # --- Family history ------------------------------------------------

    @staticmethod
    async def list_family_history(db: AsyncSession, patient_id: UUID) -> list[FamilyHistory]:
        """Live entries. Written through the medical-history form."""
        result = await db.execute(
            select(FamilyHistory)
            .where(FamilyHistory.patient_id == patient_id, _live(FamilyHistory))
            .order_by(FamilyHistory.created_at)
        )
        return list(result.scalars())

    # --- Surgical history ----------------------------------------------

    @staticmethod
    async def list_surgical_history(
        db: AsyncSession, patient_id: UUID, include_history: bool = False
    ) -> list[SurgicalHistory]:
        query = select(SurgicalHistory).where(SurgicalHistory.patient_id == patient_id)
        if not include_history:
            query = query.where(_live(SurgicalHistory))
        result = await db.execute(query.order_by(SurgicalHistory.created_at))
        return list(result.scalars())

    @staticmethod
    async def create_surgical_history(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        data: dict,
        user_id: UUID | None = None,
    ) -> SurgicalHistory:
        surgery = SurgicalHistory(
            clinic_id=clinic_id,
            patient_id=patient_id,
            **await _attribution(db, clinic_id, user_id),
            **data,
        )
        db.add(surgery)
        await db.flush()
        return surgery

    @staticmethod
    async def get_surgical_history(db: AsyncSession, surgery_id: UUID) -> SurgicalHistory | None:
        result = await db.execute(select(SurgicalHistory).where(SurgicalHistory.id == surgery_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def update_surgical_history(
        db: AsyncSession, surgery: SurgicalHistory, data: dict
    ) -> SurgicalHistory:
        for k, v in data.items():
            setattr(surgery, k, v)
        await db.flush()
        return surgery

    @staticmethod
    async def delete_surgical_history(
        db: AsyncSession, surgery: SurgicalHistory, user_id: UUID | None = None
    ) -> None:
        await PatientsClinicalService.retract_entry(db, surgery, user_id=user_id)

    # --- Emergency contact (1:1) ---------------------------------------

    @staticmethod
    async def get_emergency_contact(db: AsyncSession, patient_id: UUID) -> EmergencyContact | None:
        result = await db.execute(
            select(EmergencyContact).where(EmergencyContact.patient_id == patient_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert_emergency_contact(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID, data: dict
    ) -> EmergencyContact:
        existing = await PatientsClinicalService.get_emergency_contact(db, patient_id)
        if existing is None:
            existing = EmergencyContact(patient_id=patient_id, clinic_id=clinic_id, **data)
            db.add(existing)
        else:
            for k, v in data.items():
                setattr(existing, k, v)
        await db.flush()
        return existing

    @staticmethod
    async def delete_emergency_contact(db: AsyncSession, contact: EmergencyContact) -> None:
        await db.delete(contact)
        await db.flush()

    # --- Legal guardian (1:1) ------------------------------------------

    @staticmethod
    async def get_legal_guardian(db: AsyncSession, patient_id: UUID) -> LegalGuardian | None:
        result = await db.execute(
            select(LegalGuardian).where(LegalGuardian.patient_id == patient_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert_legal_guardian(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID, data: dict
    ) -> LegalGuardian:
        existing = await PatientsClinicalService.get_legal_guardian(db, patient_id)
        if existing is None:
            existing = LegalGuardian(patient_id=patient_id, clinic_id=clinic_id, **data)
            db.add(existing)
        else:
            for k, v in data.items():
                setattr(existing, k, v)
        await db.flush()
        return existing

    @staticmethod
    async def delete_legal_guardian(db: AsyncSession, guardian: LegalGuardian) -> None:
        await db.delete(guardian)
        await db.flush()

    # --- Aggregated views ----------------------------------------------

    @staticmethod
    async def build_medical_history(db: AsyncSession, patient_id: UUID) -> dict:
        """Return the legacy JSONB-shaped medical history payload."""
        context = await PatientsClinicalService.get_medical_context(db, patient_id)
        allergies = await PatientsClinicalService.list_allergies(db, patient_id)
        medications = await PatientsClinicalService.list_medications(db, patient_id)
        diseases = await PatientsClinicalService.list_systemic_diseases(db, patient_id)
        surgeries = await PatientsClinicalService.list_surgical_history(db, patient_id)

        ctx: dict[str, Any] = {}
        if context is not None:
            ctx = {
                "is_pregnant": context.is_pregnant,
                "pregnancy_week": context.pregnancy_week,
                "is_lactating": context.is_lactating,
                "is_on_anticoagulants": context.is_on_anticoagulants,
                "anticoagulant_medication": context.anticoagulant_medication,
                "inr_value": context.inr_value,
                "last_inr_date": context.last_inr_date,
                "is_smoker": context.is_smoker,
                "smoking_frequency": context.smoking_frequency,
                "alcohol_consumption": context.alcohol_consumption,
                "bruxism": context.bruxism,
                "adverse_reactions_to_anesthesia": context.adverse_reactions_to_anesthesia,
                "anesthesia_reaction_details": context.anesthesia_reaction_details,
                "last_updated_at": context.last_updated_at,
                "last_updated_by": context.last_updated_by,
            }
        return {
            "allergies": allergies,
            "medications": medications,
            "systemic_diseases": diseases,
            "surgical_history": surgeries,
            "family_history": await PatientsClinicalService.list_family_history(db, patient_id),
            **ctx,
        }

    @staticmethod
    async def compute_alerts(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> list[dict]:
        """Compute active alerts from normalized clinical rows."""
        context = await PatientsClinicalService.get_medical_context(db, patient_id)
        allergies = await PatientsClinicalService.list_allergies(db, patient_id)
        diseases = await PatientsClinicalService.list_systemic_diseases(db, patient_id)

        alerts: list[dict] = []

        # A class of III or more changes how the patient is treated in the
        # chair, so it is said where the allergies are said — not left in a
        # section somebody has to open.
        assessments = await PatientsClinicalService.list_asa_assessments(db, clinic_id, patient_id)
        if assessments and assessments[0].asa_class >= 3:
            current = assessments[0]
            alerts.append(
                {
                    "type": "asa",
                    "severity": "critical" if current.asa_class >= 4 else "high",
                    "title": f"ASA {current.label}",
                    "details": current.rationale,
                }
            )

        for allergy in allergies:
            if allergy.severity in ("high", "critical"):
                alerts.append(
                    {
                        "type": "allergy",
                        "severity": allergy.severity,
                        "title": f"Alergia: {allergy.name}",
                        "details": allergy.reaction,
                    }
                )

        if context is None:
            return alerts

        if context.is_pregnant:
            week = context.pregnancy_week
            alerts.append(
                {
                    "type": "pregnancy",
                    "severity": "high",
                    "title": f"Embarazada{f' ({week} semanas)' if week else ''}",
                    "details": None,
                }
            )

        if context.is_lactating:
            alerts.append(
                {
                    "type": "lactating",
                    "severity": "medium",
                    "title": "En período de lactancia",
                    "details": None,
                }
            )

        if context.is_on_anticoagulants:
            med = context.anticoagulant_medication
            inr = context.inr_value
            alerts.append(
                {
                    "type": "anticoagulant",
                    "severity": "critical",
                    "title": f"Anticoagulantes{f': {med}' if med else ''}",
                    "details": f"INR: {inr}" if inr else None,
                }
            )

        if context.adverse_reactions_to_anesthesia:
            alerts.append(
                {
                    "type": "anesthesia_reaction",
                    "severity": "critical",
                    "title": "Reacción adversa a anestesia",
                    "details": context.anesthesia_reaction_details,
                }
            )

        for disease in diseases:
            if disease.is_critical:
                alerts.append(
                    {
                        "type": "systemic_disease",
                        "severity": "high",
                        "title": disease.name,
                        "details": disease.notes,
                    }
                )

        return alerts

    # --- Bulk medical-history upsert -----------------------------------

    @staticmethod
    async def replace_medical_history(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        payload: dict,
        user_id: UUID | None,
    ) -> None:
        """Reconcile allergies/medications/diseases/surgeries and context.

        The form submits the whole block, mirroring the old JSONB shape, and
        this used to honour that literally: **every save deleted every row and
        inserted new ones**. Not a hazard reserved for a mistaken tap — the
        normal path destroyed the history on each visit, so an allergy lost the
        date it was first recorded and the record could not say since when it
        was known. Rewriting the patient's history on every save is the exact
        opposite of what ADR 0032 asks of clinical data.

        So the block is reconciled instead, matched by id:

        - a line carrying an id updates that row in place;
        - a line without one is a new entry;
        - a live row the form no longer carries is **retracted**, not deleted.

        Removal is read as a retraction rather than an end date on purpose: the
        form has no field for "when did this stop being true", and inventing
        one would put a clinical claim in the record that nobody made. A
        medication that was genuinely discontinued is ended through the entry's
        own endpoint, which can say when.

        Ids round-trip already — the form edits the object the GET returned —
        so this needs nothing from the frontend to start preserving rows.
        """
        lifecycle = {"retracted_at", "ended_at", "retraction_reason"}
        # Resolved once: the acting account is the same for the whole block.
        attribution = await _attribution(db, clinic_id, user_id)

        for table_cls, key in (
            (Allergy, "allergies"),
            (Medication, "medications"),
            (SystemicDisease, "systemic_diseases"),
            (SurgicalHistory, "surgical_history"),
            (FamilyHistory, "family_history"),
        ):
            result = await db.execute(
                select(table_cls).where(
                    table_cls.patient_id == patient_id,
                    _live(table_cls),
                )
            )
            live = {row.id: row for row in result.scalars()}
            submitted = payload.get(key) or []
            kept: set[UUID] = set()

            for row in submitted:
                fields = {
                    k: v
                    for k, v in row.items()
                    if k not in lifecycle and k not in ("id", "clinic_id", "patient_id")
                }
                existing = live.get(row.get("id")) if row.get("id") else None
                if existing is not None:
                    for field, value in fields.items():
                        setattr(existing, field, value)
                    kept.add(existing.id)
                    continue

                # An id the patient does not own is not a licence to write
                # another patient's row: it is simply not a match, and the line
                # is recorded as the new entry it looks like.
                db.add(
                    table_cls(
                        clinic_id=clinic_id,
                        patient_id=patient_id,
                        **attribution,
                        **fields,
                    )
                )

            for row_id, row in live.items():
                if row_id not in kept:
                    await PatientsClinicalService.retract_entry(
                        db, row, reason=REMOVED_FROM_FORM, user_id=user_id
                    )

        context_fields = {
            k: payload[k]
            for k in (
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
            if k in payload
        }
        await PatientsClinicalService.upsert_medical_context(
            db, clinic_id, patient_id, context_fields, user_id
        )
        await db.flush()
