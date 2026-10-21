"""Normalized medical history + emergency contact models.

Replaces the JSONB blobs (``patients.medical_history``,
``patients.emergency_contact``, ``patients.legal_guardian``) that
lived directly on the patient row before Fase B.4.

Table names are prefixed ``patients_clinical_`` so analytics queries
stay unambiguous across modules.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.core.privacy import PiiKind, pii
from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.modules.patients.models import Patient


#: ASA class → how it is written.
ASA_NUMERALS: dict[int, str] = {1: "I", 2: "II", 3: "III", 4: "IV"}


class ClinicalEntryMixin:
    """Lifecycle and attribution shared by the entries of the medical history.

    Per [ADR 0032](../../../../docs/adr/0032-clinical-record-is-append-only.md):
    a clinical entry is corrected by appending, never by deleting, and it names
    the professional responsible for it separately from the account that typed
    it.

    **"No longer true" and "never was true" are different states**, which is
    why there are two columns and not one ``deleted_at``:

    - ``ended_at`` — the fact was true and stopped being true. A medication the
      patient discontinued is history: it stays part of the record and stays
      readable, because a colleague reading the chart in 2029 needs to know it
      was taken.
    - ``retracted_at`` — the entry should never have been there: the wrong
      patient, a mistaken tap. It stops driving alerts and stops appearing in a
      disclosure, and it is *still not deleted*, because "what did the chart say
      that day" has to stay answerable.

    Collapsing the two loses the distinction that matters clinically. Neither
    removes the row.

    Attribution is two fields, for the reason it is two on a paper chart: an
    assistant may type what a dentist is responsible for.
    ``recorded_by_user_id`` is who operated the software;
    ``recorded_by_professional_id`` is who answers for it clinically, and
    through them the licence number an exported record has to show.

    The professional is resolved from the acting account's directory profile
    (``professionals.user_id``), so it fills itself in for the common case —
    the dentist recording their own patient's history. An account with no
    profile leaves it NULL, which is the truthful answer and not a gap to fill
    with a guess: an email that happens to match is a coincidence, and
    clinical authorship in a document meant to be evidence cannot rest on one.
    The case the ADR describes — an assistant typing for a dentist — needs the
    responsible professional to be *asked for*, and nothing asks yet.

    Rows recorded before the rule keep both NULL rather than being assigned an
    author who never signed them.
    """

    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    retracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    retraction_reason: Mapped[str | None] = mapped_column(Text, default=None)

    recorded_by_user_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), default=None
    )
    recorded_by_professional_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("professionals.id"), default=None
    )

    @property
    def is_live(self) -> bool:
        """Currently true and never retracted — what a form shows by default."""
        return self.ended_at is None and self.retracted_at is None


class MedicalContext(Base, TimestampMixin):
    """1:1 medical flags + anesthesia + lifestyle context for a patient."""

    __tablename__ = "patients_clinical_medical_context"

    patient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        primary_key=True,
    )
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    is_pregnant: Mapped[bool] = mapped_column(Boolean, default=False)
    pregnancy_week: Mapped[int | None] = mapped_column(Integer)
    is_lactating: Mapped[bool] = mapped_column(Boolean, default=False)

    is_on_anticoagulants: Mapped[bool] = mapped_column(Boolean, default=False)
    anticoagulant_medication: Mapped[str | None] = mapped_column(String(100))
    inr_value: Mapped[float | None] = mapped_column(Float)
    last_inr_date: Mapped[date | None] = mapped_column(Date)

    is_smoker: Mapped[bool] = mapped_column(Boolean, default=False)
    smoking_frequency: Mapped[str | None] = mapped_column(String(100))
    alcohol_consumption: Mapped[str | None] = mapped_column(String(100))

    bruxism: Mapped[bool] = mapped_column(Boolean, default=False)

    adverse_reactions_to_anesthesia: Mapped[bool] = mapped_column(Boolean, default=False)
    anesthesia_reaction_details: Mapped[str | None] = mapped_column(String(500))

    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_updated_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True))

    patient: Mapped[Patient] = relationship()


class Allergy(Base, TimestampMixin, ClinicalEntryMixin):
    """Individual allergy entry (N:1 patient)."""

    __tablename__ = "patients_clinical_allergy"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    patient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str | None] = mapped_column(String(50))
    # severity: low | medium | high | critical
    severity: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    reaction: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)


class Medication(Base, TimestampMixin, ClinicalEntryMixin):
    """Medication the patient is currently taking (N:1)."""

    __tablename__ = "patients_clinical_medication"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    patient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    name: Mapped[str] = mapped_column(String(100))
    dosage: Mapped[str | None] = mapped_column(String(100))
    frequency: Mapped[str | None] = mapped_column(String(100))
    start_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class SystemicDisease(Base, TimestampMixin, ClinicalEntryMixin):
    """Systemic disease / condition (N:1)."""

    __tablename__ = "patients_clinical_systemic_disease"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    patient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str | None] = mapped_column(String(50))
    diagnosis_date: Mapped[date | None] = mapped_column(Date)
    is_controlled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    medications: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class SurgicalHistory(Base, TimestampMixin, ClinicalEntryMixin):
    """Past surgery / procedure (N:1)."""

    __tablename__ = "patients_clinical_surgical_history"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    patient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    procedure: Mapped[str] = mapped_column(String(200))
    surgery_date: Mapped[date | None] = mapped_column(Date)
    complications: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


FAMILY_RELATIVES = ("mother", "father", "sibling", "grandparent", "child", "other")


class FamilyHistory(Base, TimestampMixin, ClinicalEntryMixin):
    """A condition that runs in the patient's family (N:1).

    The *antecedentes heredo-familiares* of a clinical history: what a
    relative has or had, and which relative.
    """

    __tablename__ = "patients_clinical_family_history"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    patient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    condition: Mapped[str] = mapped_column(String(200))
    #: Which relative, as a kind — never a name.
    relative: Mapped[str] = mapped_column(String(20), default="other")
    notes: Mapped[str | None] = mapped_column(Text)


class HealthQuestionnaire(Base, TimestampMixin, ClinicalEntryMixin):
    """What the patient declared at a visit, as they declared it (N:1).

    A dated statement, not the curated history: the allergies, medications
    and diseases a clinician keeps live in their own tables and move on.
    This says what the patient answered *that day* and never changes — a
    new visit is a new questionnaire, and a mistaken one is retracted.

    Filled in on screen (``answers`` and ``conditions`` hold it) or on the
    printed form, in which case ``scan_document_id`` is the sheet and the
    answers are on it.
    """

    __tablename__ = "patients_clinical_health_questionnaire"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    patient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    form_version: Mapped[str] = mapped_column(String(10))
    #: Which form was answered: ``adult``, or ``pediatric`` — the one a
    #: parent or guardian answers and signs for a child
    #: (``questionnaire.FORMS``).
    form_kind: Mapped[str] = mapped_column(String(20), default="adult", server_default="adult")
    #: What the pediatric form asks to write rather than answer yes or no
    #: (school, guardian, weight…): ``{field_key: text}``. The guardian's
    #: name and phone are in it, so it is classified like a name.
    form_data: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}", info=pii(PiiKind.NAME)
    )
    #: Why the patient came, in their words.
    chief_complaint: Mapped[str | None] = mapped_column(Text)
    blood_type: Mapped[str | None] = mapped_column(String(10))
    declared_allergies: Mapped[str | None] = mapped_column(Text)

    #: ``{question_key: {"answer": bool, "detail": str | None}}``. A question
    #: left unanswered is absent — "not asked" is not "no".
    answers: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: Keys of the conditions ticked.
    conditions: Mapped[list] = mapped_column(JSONB, default=list)
    drugs_detail: Mapped[str | None] = mapped_column(String(300))
    other_conditions: Mapped[str | None] = mapped_column(Text)

    #: The scanned sheet, when it was filled in by hand. An id among the
    #: patient's documents, checked through ``PatientDocuments``.
    scan_document_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True))

    # The patient's signature, when the questionnaire was answered on
    # screen and signed there. On paper the signature is on the scan.
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_by_name: Mapped[str | None] = mapped_column(String(200), info=pii(PiiKind.NAME))
    #: In what capacity they signed: the patient, or someone for them.
    signer_capacity: Mapped[str | None] = mapped_column(String(20))
    #: ``{"png": "data:image/png;base64,…"}``: the drawing, as it was made.
    #: Classified like a name — it identifies the person as surely as one —
    #: so an erasure request removes the drawing too.
    signature_data: Mapped[dict | None] = mapped_column(JSONB, info=pii(PiiKind.NAME))
    #: The regulation the form named when it was signed — the clinic may
    #: change the line later, and what was signed under must not move.
    regulation: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (
        CheckConstraint(
            "form_kind IN ('adult', 'pediatric')", name="ck_health_questionnaire_form_kind"
        ),
    )


class AsaAssessment(Base, TimestampMixin, ClinicalEntryMixin):
    """An ASA physical status, as a clinician judged it on a given day (N:1).

    A judgement, not a property of the patient: who was ASA II before a
    cardiac event is not retroactively ASA III. So it is never edited — a
    new assessment supersedes the previous one, and the newest that was
    not retracted is the patient's current class.

    ``ended_at`` is not used: an assessment does not stop being true, it
    is followed by another.
    """

    __tablename__ = "patients_clinical_asa_assessment"
    __table_args__ = (CheckConstraint("asa_class BETWEEN 1 AND 4", name="ck_asa_assessment_class"),)

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    patient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
    )
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: 1–4, the ASA Physical Status class (I–IV). The scale goes on to V
    #: and VI — a moribund patient, a declared brain death — which are not
    #: patients of a dental practice, so they are not offered.
    asa_class: Mapped[int] = mapped_column(Integer)
    #: The ``E`` modifier: assessed for an emergency procedure.
    is_emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    #: What the class rests on, in the assessor's words.
    rationale: Mapped[str | None] = mapped_column(Text)

    @property
    def label(self) -> str:
        """``III``, ``IIE``: the class as it is written."""
        return ASA_NUMERALS[self.asa_class] + ("E" if self.is_emergency else "")


class EmergencyContact(Base, TimestampMixin):
    """Emergency contact (1:1)."""

    __tablename__ = "patients_clinical_emergency_contact"

    patient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        primary_key=True,
    )
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    name: Mapped[str] = mapped_column(String(100), info=pii(PiiKind.NAME))
    relationship: Mapped[str | None] = mapped_column(String(50))
    phone: Mapped[str] = mapped_column(String(20), info=pii(PiiKind.PHONE))
    email: Mapped[str | None] = mapped_column(String(255), info=pii(PiiKind.EMAIL))
    is_legal_guardian: Mapped[bool] = mapped_column(Boolean, default=False)


class LegalGuardian(Base, TimestampMixin):
    """Legal guardian (1:1, for minors or incapacitated patients)."""

    __tablename__ = "patients_clinical_legal_guardian"

    patient_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        primary_key=True,
    )
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    name: Mapped[str] = mapped_column(String(100), info=pii(PiiKind.NAME))
    relationship: Mapped[str] = mapped_column(String(50))
    # Named after the Spanish document; holds whichever one the guardian
    # carries, so it is classified by role rather than by that name.
    dni: Mapped[str | None] = mapped_column(String(20), info=pii(PiiKind.NATIONAL_ID))
    phone: Mapped[str] = mapped_column(String(20), info=pii(PiiKind.PHONE))
    email: Mapped[str | None] = mapped_column(String(255), info=pii(PiiKind.EMAIL))
    address: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
