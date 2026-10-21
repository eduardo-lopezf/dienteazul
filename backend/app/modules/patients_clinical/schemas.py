"""Pydantic schemas for the patients_clinical module."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# --- Medical context -----------------------------------------------------


class MedicalContextBase(BaseModel):
    is_pregnant: bool = False
    pregnancy_week: int | None = Field(default=None, ge=1, le=42)
    is_lactating: bool = False

    is_on_anticoagulants: bool = False
    anticoagulant_medication: str | None = Field(default=None, max_length=100)
    inr_value: float | None = Field(default=None, ge=0, le=20)
    last_inr_date: date | None = None

    is_smoker: bool = False
    smoking_frequency: str | None = Field(default=None, max_length=100)
    alcohol_consumption: str | None = Field(default=None, max_length=100)

    bruxism: bool = False

    adverse_reactions_to_anesthesia: bool = False
    anesthesia_reaction_details: str | None = Field(default=None, max_length=500)


class MedicalContextUpdate(MedicalContextBase):
    pass


class MedicalContextResponse(MedicalContextBase):
    last_updated_at: datetime | None = None
    last_updated_by: UUID | None = None

    model_config = ConfigDict(from_attributes=True)


# --- Allergy ------------------------------------------------------------


class AllergyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str | None = Field(default=None, max_length=50)
    severity: str = Field(default="medium", max_length=20)
    reaction: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class AllergyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: str | None = Field(default=None, max_length=50)
    severity: str | None = Field(default=None, max_length=20)
    reaction: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class AllergyResponse(AllergyCreate):
    id: UUID

    model_config = ConfigDict(from_attributes=True)


# --- Medication ---------------------------------------------------------


class MedicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dosage: str | None = Field(default=None, max_length=100)
    frequency: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    notes: str | None = None


class MedicationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    dosage: str | None = Field(default=None, max_length=100)
    frequency: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    notes: str | None = None


class MedicationResponse(MedicationCreate):
    id: UUID

    model_config = ConfigDict(from_attributes=True)


# --- Systemic disease ---------------------------------------------------


class SystemicDiseaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str | None = Field(default=None, max_length=50)
    diagnosis_date: date | None = None
    is_controlled: bool = True
    is_critical: bool = False
    medications: str | None = None
    notes: str | None = None


class SystemicDiseaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: str | None = Field(default=None, max_length=50)
    diagnosis_date: date | None = None
    is_controlled: bool | None = None
    is_critical: bool | None = None
    medications: str | None = None
    notes: str | None = None


class SystemicDiseaseResponse(SystemicDiseaseCreate):
    id: UUID

    model_config = ConfigDict(from_attributes=True)


# --- Surgical history ---------------------------------------------------


class SurgicalHistoryCreate(BaseModel):
    procedure: str = Field(min_length=1, max_length=200)
    surgery_date: date | None = None
    complications: str | None = None
    notes: str | None = None


class SurgicalHistoryUpdate(BaseModel):
    procedure: str | None = Field(default=None, min_length=1, max_length=200)
    surgery_date: date | None = None
    complications: str | None = None
    notes: str | None = None


class SurgicalHistoryResponse(SurgicalHistoryCreate):
    id: UUID

    model_config = ConfigDict(from_attributes=True)


# --- Family history -----------------------------------------------------

Relative = Literal["mother", "father", "sibling", "grandparent", "child", "other"]


class FamilyHistoryCreate(BaseModel):
    condition: str = Field(min_length=1, max_length=200)
    relative: Relative = "other"
    notes: str | None = None


class FamilyHistoryResponse(FamilyHistoryCreate):
    id: UUID

    model_config = ConfigDict(from_attributes=True)


# --- Health questionnaire ----------------------------------------------


class QuestionAnswer(BaseModel):
    answer: bool
    detail: str | None = Field(default=None, max_length=500)


SignerCapacity = Literal["patient", "guardian", "representative"]

#: Which form: the adult one, or the pediatric one a guardian signs
#: (``questionnaire.FORMS``).
FormKind = Literal["adult", "pediatric"]

#: A drawn signature is a few kilobytes; this is room to spare and a lid.
_SIGNATURE_MAX_CHARS = 400_000


class QuestionnaireSignature(BaseModel):
    """The patient's signature, drawn on screen."""

    png: str = Field(max_length=_SIGNATURE_MAX_CHARS)
    signed_by_name: str = Field(min_length=1, max_length=200)
    signer_capacity: SignerCapacity = "patient"

    @field_validator("png")
    @classmethod
    def _is_a_png(cls, value: str) -> str:
        if not value.startswith("data:image/png;base64,"):
            raise ValueError("The signature must be a PNG data URL")
        return value


class HealthQuestionnaireCreate(BaseModel):
    """What the patient declared, or the scan of the sheet they filled in."""

    taken_at: datetime | None = None
    form_kind: FormKind = "adult"
    #: Pediatric form only: what it asks to write (``PEDIATRIC_FIELD_GROUPS``).
    form_data: dict[str, Annotated[str, Field(max_length=300)]] = {}
    chief_complaint: str | None = Field(default=None, max_length=2000)
    blood_type: str | None = Field(default=None, max_length=10)
    declared_allergies: str | None = Field(default=None, max_length=2000)
    answers: dict[str, QuestionAnswer] = {}
    conditions: list[str] = []
    drugs_detail: str | None = Field(default=None, max_length=300)
    other_conditions: str | None = Field(default=None, max_length=2000)
    scan_document_id: UUID | None = None
    #: On screen only: a sheet filled in by hand carries its own.
    signature: QuestionnaireSignature | None = None


class HealthQuestionnaireResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    taken_at: datetime
    form_version: str
    form_kind: str = "adult"
    form_data: dict[str, str] = {}
    chief_complaint: str | None
    blood_type: str | None
    declared_allergies: str | None
    answers: dict[str, QuestionAnswer]
    conditions: list[str]
    drugs_detail: str | None
    other_conditions: str | None
    scan_document_id: UUID | None
    signed_at: datetime | None
    signed_by_name: str | None
    signer_capacity: str | None
    #: ``{"png": …}``: the drawing, for whoever reads the questionnaire.
    signature_data: dict | None
    #: The regulation the form named when it was recorded.
    regulation: str | None
    retracted_at: datetime | None
    recorded_by_professional_id: UUID | None
    created_at: datetime


# --- ASA physical status -------------------------------------------------


class AsaAssessmentCreate(BaseModel):
    """A clinician's judgement of the patient's physical status, today."""

    asa_class: int = Field(ge=1, le=4)
    is_emergency: bool = False
    rationale: str | None = Field(default=None, max_length=2000)
    assessed_at: datetime | None = None


class AsaAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    assessed_at: datetime
    asa_class: int
    is_emergency: bool
    #: ``III``, ``IIE``: the class as it is written.
    label: str
    rationale: str | None
    retracted_at: datetime | None
    recorded_by_professional_id: UUID | None
    #: Who answers for it, when the directory knows them.
    assessed_by_name: str | None = None
    created_at: datetime


class AsaClassResponse(BaseModel):
    """The current class and nothing else: what reception sees when booking.

    Deliberately without the date, the reason, the assessor or the
    history — those are the medical history's, behind ``medical.read``.
    """

    #: None when nobody assessed the patient.
    asa_class: int | None
    label: str | None
    is_emergency: bool


class AsaStatusResponse(BaseModel):
    """The patient's current class and the assessments behind it."""

    #: The newest assessment that was not retracted. None: never assessed.
    current: AsaAssessmentResponse | None
    #: Every assessment that was not retracted, newest first.
    history: list[AsaAssessmentResponse]


class RetractRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


# --- Emergency contact --------------------------------------------------


class EmergencyContactBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    relationship: str | None = Field(default=None, max_length=50)
    phone: str = Field(min_length=1, max_length=20)
    email: EmailStr | None = None
    is_legal_guardian: bool = False


class EmergencyContactUpsert(EmergencyContactBase):
    pass


class EmergencyContactResponse(EmergencyContactBase):
    model_config = ConfigDict(from_attributes=True)


# --- Legal guardian -----------------------------------------------------


class LegalGuardianBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    relationship: str = Field(max_length=50)
    dni: str | None = Field(default=None, max_length=20)
    phone: str = Field(min_length=1, max_length=20)
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=200)
    notes: str | None = None


class LegalGuardianUpsert(LegalGuardianBase):
    pass


class LegalGuardianResponse(LegalGuardianBase):
    model_config = ConfigDict(from_attributes=True)


# --- Aggregate medical history (legacy-shaped payload for the form) -----


# The bulk payload carries ids, the per-row create endpoints do not.
#
# The form edits the very objects the GET returned, so each line already knows
# which row it is — but the payload was validated against the create schemas,
# which have no `id`, and Pydantic dropped it. With the id gone the backend
# could only replace the whole block, which is how a save came to delete and
# recreate a patient's history. An id is optional: a line typed into the form
# a moment ago does not have one yet.


class AllergySubmit(AllergyCreate):
    id: UUID | None = None


class MedicationSubmit(MedicationCreate):
    id: UUID | None = None


class SystemicDiseaseSubmit(SystemicDiseaseCreate):
    id: UUID | None = None


class SurgicalHistorySubmit(SurgicalHistoryCreate):
    id: UUID | None = None


class FamilyHistorySubmit(FamilyHistoryCreate):
    id: UUID | None = None


class MedicalHistoryUpdate(BaseModel):
    """Bulk update payload mirroring the legacy JSONB shape.

    The frontend form submits the entire medical history in one go. The
    backend reconciles it against the stored rows — matching on id, inserting
    what is new, retracting what the form dropped — rather than replacing the
    block, which used to destroy every row on every save.
    """

    allergies: list[AllergySubmit] = []
    medications: list[MedicationSubmit] = []
    systemic_diseases: list[SystemicDiseaseSubmit] = []
    surgical_history: list[SurgicalHistorySubmit] = []
    family_history: list[FamilyHistorySubmit] = []

    is_pregnant: bool = False
    pregnancy_week: int | None = Field(default=None, ge=1, le=42)
    is_lactating: bool = False

    is_on_anticoagulants: bool = False
    anticoagulant_medication: str | None = Field(default=None, max_length=100)
    inr_value: float | None = Field(default=None, ge=0, le=20)
    last_inr_date: date | None = None

    is_smoker: bool = False
    smoking_frequency: str | None = Field(default=None, max_length=100)
    alcohol_consumption: str | None = Field(default=None, max_length=100)

    bruxism: bool = False

    adverse_reactions_to_anesthesia: bool = False
    anesthesia_reaction_details: str | None = Field(default=None, max_length=500)


class MedicalHistoryResponse(BaseModel):
    allergies: list[AllergyResponse] = []
    medications: list[MedicationResponse] = []
    systemic_diseases: list[SystemicDiseaseResponse] = []
    surgical_history: list[SurgicalHistoryResponse] = []
    family_history: list[FamilyHistoryResponse] = []

    is_pregnant: bool = False
    pregnancy_week: int | None = None
    is_lactating: bool = False

    is_on_anticoagulants: bool = False
    anticoagulant_medication: str | None = None
    inr_value: float | None = None
    last_inr_date: date | None = None

    is_smoker: bool = False
    smoking_frequency: str | None = None
    alcohol_consumption: str | None = None

    bruxism: bool = False

    adverse_reactions_to_anesthesia: bool = False
    anesthesia_reaction_details: str | None = None

    last_updated_at: datetime | None = None
    last_updated_by: UUID | None = None


# --- Alerts (computed) --------------------------------------------------


class PatientAlert(BaseModel):
    type: str
    severity: str
    title: str
    details: str | None = None


class PatientAlertsResponse(BaseModel):
    alerts: list[PatientAlert]
