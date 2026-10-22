"""HTTP surface for patients_clinical.

Mounted under ``/api/v1/patients_clinical/*``. Endpoints are scoped by
``patient_id`` path parameter; each verifies the patient belongs to
the caller's clinic before touching clinical rows.

The legacy ``/medical-history`` bulk endpoint stays — the form still
submits the whole blob — but it now writes normalized rows atomically.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.contracts import ProfessionalDirectory, provider
from app.core.events import EventType, event_bus
from app.core.schemas import ApiResponse
from app.database import get_db
from app.modules.patients.service import PatientService

from .errors import record_not_found, rejected
from .questionnaire_pdf import render_blank_pdf
from .schemas import (
    AllergyCreate,
    AllergyResponse,
    AllergyUpdate,
    AsaAssessmentCreate,
    AsaAssessmentResponse,
    AsaClassResponse,
    AsaStatusResponse,
    EmergencyContactResponse,
    EmergencyContactUpsert,
    HealthQuestionnaireCreate,
    HealthQuestionnaireResponse,
    LegalGuardianResponse,
    LegalGuardianUpsert,
    MedicalContextResponse,
    MedicalContextUpdate,
    MedicalHistoryResponse,
    MedicalHistoryUpdate,
    MedicationCreate,
    MedicationResponse,
    MedicationUpdate,
    PatientAlertsResponse,
    RetractRequest,
    SurgicalHistoryCreate,
    SurgicalHistoryResponse,
    SurgicalHistoryUpdate,
    SystemicDiseaseCreate,
    SystemicDiseaseResponse,
    SystemicDiseaseUpdate,
)
from .service import PatientsClinicalService

router = APIRouter()


async def _ensure_patient(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> None:
    patient = await PatientService.get_patient(db, clinic_id, patient_id)
    if patient is None:
        raise record_not_found("patient", "Patient")


# --- Medical context (1:1) ----------------------------------------------


@router.get(
    "/patients/{patient_id}/medical-context",
    response_model=ApiResponse[MedicalContextResponse],
)
async def get_medical_context(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[MedicalContextResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    ctx_row = await PatientsClinicalService.get_medical_context(db, patient_id)
    if ctx_row is None:
        return ApiResponse(data=MedicalContextResponse())
    return ApiResponse(data=MedicalContextResponse.model_validate(ctx_row))


@router.put(
    "/patients/{patient_id}/medical-context",
    response_model=ApiResponse[MedicalContextResponse],
)
async def update_medical_context(
    patient_id: UUID,
    data: MedicalContextUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[MedicalContextResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    ctx_row = await PatientsClinicalService.upsert_medical_context(
        db, ctx.clinic_id, patient_id, data.model_dump(exclude_unset=True), ctx.user_id
    )
    await db.commit()
    await db.refresh(ctx_row)
    event_bus.publish_after_commit(
        db,
        EventType.PATIENT_MEDICAL_UPDATED,
        {
            "patient_id": str(patient_id),
            "clinic_id": str(ctx.clinic_id),
            "user_id": str(ctx.user_id),
            "section": "context",
            "summary": "Contexto médico actualizado",
        },
    )
    return ApiResponse(data=MedicalContextResponse.model_validate(ctx_row))


# --- Allergies ---------------------------------------------------------


@router.get(
    "/patients/{patient_id}/allergies",
    response_model=ApiResponse[list[AllergyResponse]],
)
async def list_allergies(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[AllergyResponse]]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    allergies = await PatientsClinicalService.list_allergies(db, patient_id)
    return ApiResponse(data=[AllergyResponse.model_validate(a) for a in allergies])


@router.post(
    "/patients/{patient_id}/allergies",
    response_model=ApiResponse[AllergyResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_allergy(
    patient_id: UUID,
    data: AllergyCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AllergyResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    allergy = await PatientsClinicalService.create_allergy(
        db, ctx.clinic_id, patient_id, data.model_dump(), user_id=ctx.user_id
    )
    await db.commit()
    await db.refresh(allergy)
    return ApiResponse(data=AllergyResponse.model_validate(allergy))


@router.put(
    "/patients/{patient_id}/allergies/{allergy_id}",
    response_model=ApiResponse[AllergyResponse],
)
async def update_allergy(
    patient_id: UUID,
    allergy_id: UUID,
    data: AllergyUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AllergyResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    allergy = await PatientsClinicalService.get_allergy(db, allergy_id)
    if allergy is None or allergy.patient_id != patient_id:
        raise record_not_found("allergy", "Allergy")
    allergy = await PatientsClinicalService.update_allergy(
        db, allergy, data.model_dump(exclude_unset=True)
    )
    await db.commit()
    await db.refresh(allergy)
    return ApiResponse(data=AllergyResponse.model_validate(allergy))


@router.delete(
    "/patients/{patient_id}/allergies/{allergy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_allergy(
    patient_id: UUID,
    allergy_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    allergy = await PatientsClinicalService.get_allergy(db, allergy_id)
    if allergy is None or allergy.patient_id != patient_id:
        raise record_not_found("allergy", "Allergy")
    await PatientsClinicalService.delete_allergy(db, allergy, user_id=ctx.user_id)
    await db.commit()


# --- Medications -------------------------------------------------------


@router.get(
    "/patients/{patient_id}/medications",
    response_model=ApiResponse[list[MedicationResponse]],
)
async def list_medications(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[MedicationResponse]]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    meds = await PatientsClinicalService.list_medications(db, patient_id)
    return ApiResponse(data=[MedicationResponse.model_validate(m) for m in meds])


@router.post(
    "/patients/{patient_id}/medications",
    response_model=ApiResponse[MedicationResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_medication(
    patient_id: UUID,
    data: MedicationCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[MedicationResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    med = await PatientsClinicalService.create_medication(
        db, ctx.clinic_id, patient_id, data.model_dump(), user_id=ctx.user_id
    )
    await db.commit()
    await db.refresh(med)
    return ApiResponse(data=MedicationResponse.model_validate(med))


@router.put(
    "/patients/{patient_id}/medications/{medication_id}",
    response_model=ApiResponse[MedicationResponse],
)
async def update_medication(
    patient_id: UUID,
    medication_id: UUID,
    data: MedicationUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[MedicationResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    med = await PatientsClinicalService.get_medication(db, medication_id)
    if med is None or med.patient_id != patient_id:
        raise record_not_found("medication", "Medication")
    med = await PatientsClinicalService.update_medication(
        db, med, data.model_dump(exclude_unset=True)
    )
    await db.commit()
    await db.refresh(med)
    return ApiResponse(data=MedicationResponse.model_validate(med))


@router.delete(
    "/patients/{patient_id}/medications/{medication_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_medication(
    patient_id: UUID,
    medication_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    med = await PatientsClinicalService.get_medication(db, medication_id)
    if med is None or med.patient_id != patient_id:
        raise record_not_found("medication", "Medication")
    await PatientsClinicalService.delete_medication(db, med, user_id=ctx.user_id)
    await db.commit()


# --- Systemic diseases -------------------------------------------------


@router.get(
    "/patients/{patient_id}/systemic-diseases",
    response_model=ApiResponse[list[SystemicDiseaseResponse]],
)
async def list_systemic_diseases(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[SystemicDiseaseResponse]]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    rows = await PatientsClinicalService.list_systemic_diseases(db, patient_id)
    return ApiResponse(data=[SystemicDiseaseResponse.model_validate(r) for r in rows])


@router.post(
    "/patients/{patient_id}/systemic-diseases",
    response_model=ApiResponse[SystemicDiseaseResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_systemic_disease(
    patient_id: UUID,
    data: SystemicDiseaseCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SystemicDiseaseResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    disease = await PatientsClinicalService.create_systemic_disease(
        db, ctx.clinic_id, patient_id, data.model_dump(), user_id=ctx.user_id
    )
    await db.commit()
    await db.refresh(disease)
    return ApiResponse(data=SystemicDiseaseResponse.model_validate(disease))


@router.put(
    "/patients/{patient_id}/systemic-diseases/{disease_id}",
    response_model=ApiResponse[SystemicDiseaseResponse],
)
async def update_systemic_disease(
    patient_id: UUID,
    disease_id: UUID,
    data: SystemicDiseaseUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SystemicDiseaseResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    disease = await PatientsClinicalService.get_systemic_disease(db, disease_id)
    if disease is None or disease.patient_id != patient_id:
        raise record_not_found("disease", "Disease")
    disease = await PatientsClinicalService.update_systemic_disease(
        db, disease, data.model_dump(exclude_unset=True)
    )
    await db.commit()
    await db.refresh(disease)
    return ApiResponse(data=SystemicDiseaseResponse.model_validate(disease))


@router.delete(
    "/patients/{patient_id}/systemic-diseases/{disease_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_systemic_disease(
    patient_id: UUID,
    disease_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    disease = await PatientsClinicalService.get_systemic_disease(db, disease_id)
    if disease is None or disease.patient_id != patient_id:
        raise record_not_found("disease", "Disease")
    await PatientsClinicalService.delete_systemic_disease(db, disease, user_id=ctx.user_id)
    await db.commit()


# --- Surgical history --------------------------------------------------


@router.get(
    "/patients/{patient_id}/surgical-history",
    response_model=ApiResponse[list[SurgicalHistoryResponse]],
)
async def list_surgical_history(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[SurgicalHistoryResponse]]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    rows = await PatientsClinicalService.list_surgical_history(db, patient_id)
    return ApiResponse(data=[SurgicalHistoryResponse.model_validate(r) for r in rows])


@router.post(
    "/patients/{patient_id}/surgical-history",
    response_model=ApiResponse[SurgicalHistoryResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_surgical_history(
    patient_id: UUID,
    data: SurgicalHistoryCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SurgicalHistoryResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    surgery = await PatientsClinicalService.create_surgical_history(
        db, ctx.clinic_id, patient_id, data.model_dump(), user_id=ctx.user_id
    )
    await db.commit()
    await db.refresh(surgery)
    return ApiResponse(data=SurgicalHistoryResponse.model_validate(surgery))


@router.put(
    "/patients/{patient_id}/surgical-history/{surgery_id}",
    response_model=ApiResponse[SurgicalHistoryResponse],
)
async def update_surgical_history(
    patient_id: UUID,
    surgery_id: UUID,
    data: SurgicalHistoryUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SurgicalHistoryResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    surgery = await PatientsClinicalService.get_surgical_history(db, surgery_id)
    if surgery is None or surgery.patient_id != patient_id:
        raise record_not_found("surgery", "Surgery")
    surgery = await PatientsClinicalService.update_surgical_history(
        db, surgery, data.model_dump(exclude_unset=True)
    )
    await db.commit()
    await db.refresh(surgery)
    return ApiResponse(data=SurgicalHistoryResponse.model_validate(surgery))


@router.delete(
    "/patients/{patient_id}/surgical-history/{surgery_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_surgical_history(
    patient_id: UUID,
    surgery_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    surgery = await PatientsClinicalService.get_surgical_history(db, surgery_id)
    if surgery is None or surgery.patient_id != patient_id:
        raise record_not_found("surgery", "Surgery")
    await PatientsClinicalService.delete_surgical_history(db, surgery, user_id=ctx.user_id)
    await db.commit()


# --- Emergency contact (1:1) -------------------------------------------


@router.get(
    "/patients/{patient_id}/emergency-contact",
    response_model=ApiResponse[EmergencyContactResponse | None],
)
async def get_emergency_contact(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.emergency.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[EmergencyContactResponse | None]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    contact = await PatientsClinicalService.get_emergency_contact(db, patient_id)
    if contact is None:
        return ApiResponse(data=None)
    return ApiResponse(data=EmergencyContactResponse.model_validate(contact))


@router.put(
    "/patients/{patient_id}/emergency-contact",
    response_model=ApiResponse[EmergencyContactResponse],
)
async def upsert_emergency_contact(
    patient_id: UUID,
    data: EmergencyContactUpsert,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.emergency.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[EmergencyContactResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    contact = await PatientsClinicalService.upsert_emergency_contact(
        db, ctx.clinic_id, patient_id, data.model_dump()
    )
    await db.commit()
    await db.refresh(contact)
    return ApiResponse(data=EmergencyContactResponse.model_validate(contact))


@router.delete(
    "/patients/{patient_id}/emergency-contact",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_emergency_contact(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.emergency.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    contact = await PatientsClinicalService.get_emergency_contact(db, patient_id)
    if contact is None:
        raise record_not_found("emergency_contact", "Emergency contact")
    await PatientsClinicalService.delete_emergency_contact(db, contact)
    await db.commit()


# --- Legal guardian (1:1) ----------------------------------------------


@router.get(
    "/patients/{patient_id}/legal-guardian",
    response_model=ApiResponse[LegalGuardianResponse | None],
)
async def get_legal_guardian(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.emergency.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LegalGuardianResponse | None]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    guardian = await PatientsClinicalService.get_legal_guardian(db, patient_id)
    if guardian is None:
        return ApiResponse(data=None)
    return ApiResponse(data=LegalGuardianResponse.model_validate(guardian))


@router.put(
    "/patients/{patient_id}/legal-guardian",
    response_model=ApiResponse[LegalGuardianResponse],
)
async def upsert_legal_guardian(
    patient_id: UUID,
    data: LegalGuardianUpsert,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.emergency.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LegalGuardianResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    guardian = await PatientsClinicalService.upsert_legal_guardian(
        db, ctx.clinic_id, patient_id, data.model_dump()
    )
    await db.commit()
    await db.refresh(guardian)
    return ApiResponse(data=LegalGuardianResponse.model_validate(guardian))


@router.delete(
    "/patients/{patient_id}/legal-guardian",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_legal_guardian(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.emergency.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    guardian = await PatientsClinicalService.get_legal_guardian(db, patient_id)
    if guardian is None:
        raise record_not_found("legal_guardian", "Legal guardian")
    await PatientsClinicalService.delete_legal_guardian(db, guardian)
    await db.commit()


# --- Aggregated medical history + alerts -------------------------------


@router.get(
    "/patients/{patient_id}/medical-history",
    response_model=ApiResponse[MedicalHistoryResponse],
)
async def get_medical_history(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[MedicalHistoryResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    data = await PatientsClinicalService.build_medical_history(db, patient_id)
    return ApiResponse(data=MedicalHistoryResponse.model_validate(data))


@router.put(
    "/patients/{patient_id}/medical-history",
    response_model=ApiResponse[MedicalHistoryResponse],
)
async def replace_medical_history(
    patient_id: UUID,
    data: MedicalHistoryUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[MedicalHistoryResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    await PatientsClinicalService.replace_medical_history(
        db,
        ctx.clinic_id,
        patient_id,
        data.model_dump(),
        ctx.user_id,
    )
    await db.commit()
    event_bus.publish_after_commit(
        db,
        EventType.PATIENT_MEDICAL_UPDATED,
        {
            "patient_id": str(patient_id),
            "clinic_id": str(ctx.clinic_id),
            "user_id": str(ctx.user_id),
            "section": "history",
            "summary": "Historial médico actualizado",
        },
    )
    refreshed = await PatientsClinicalService.build_medical_history(db, patient_id)
    return ApiResponse(data=MedicalHistoryResponse.model_validate(refreshed))


@router.get(
    "/patients/{patient_id}/alerts",
    response_model=ApiResponse[PatientAlertsResponse],
)
async def get_patient_alerts(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PatientAlertsResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    alerts = await PatientsClinicalService.compute_alerts(db, ctx.clinic_id, patient_id)
    return ApiResponse(data=PatientAlertsResponse(alerts=alerts))


# --- ASA physical status --------------------------------------------------


async def _asa_responses(
    db: AsyncSession, clinic_id: UUID, assessments: list
) -> list[AsaAssessmentResponse]:
    """Assessments as the API answers them, each naming who made it.

    The name comes from the directory through its contract (ADR 0039); with
    the Professionals App off, or for an account with no profile, it is
    left blank.
    """
    directory = provider(ProfessionalDirectory)
    ids = {a.recorded_by_professional_id for a in assessments if a.recorded_by_professional_id}
    briefs = await directory.briefs(db, clinic_id, ids) if directory and ids else {}
    responses = []
    for assessment in assessments:
        response = AsaAssessmentResponse.model_validate(assessment)
        brief = briefs.get(assessment.recorded_by_professional_id)
        if brief is not None:
            response.assessed_by_name = f"{brief.first_name} {brief.last_name}".strip()
        responses.append(response)
    return responses


@router.get("/patients/{patient_id}/asa", response_model=ApiResponse[AsaStatusResponse])
async def get_asa_status(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AsaStatusResponse]:
    """The patient's current ASA class and the assessments behind it."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    rows = await PatientsClinicalService.list_asa_assessments(db, ctx.clinic_id, patient_id)
    history = await _asa_responses(db, ctx.clinic_id, rows)
    return ApiResponse(
        data=AsaStatusResponse(current=history[0] if history else None, history=history)
    )


@router.get("/patients/{patient_id}/asa/class", response_model=ApiResponse[AsaClassResponse])
async def get_asa_class(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.asa.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AsaClassResponse]:
    """The patient's current ASA class, alone — for whoever books them."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    rows = await PatientsClinicalService.list_asa_assessments(db, ctx.clinic_id, patient_id)
    current = rows[0] if rows else None
    return ApiResponse(
        data=AsaClassResponse(
            asa_class=current.asa_class if current else None,
            label=current.label if current else None,
            is_emergency=current.is_emergency if current else False,
        )
    )


@router.post(
    "/patients/{patient_id}/asa",
    response_model=ApiResponse[AsaAssessmentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_asa_assessment(
    patient_id: UUID,
    data: AsaAssessmentCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.asa.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AsaAssessmentResponse]:
    """Assess the patient's physical status. Earlier assessments are kept."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        assessment = await PatientsClinicalService.create_asa_assessment(
            db, ctx.clinic_id, patient_id, data.model_dump(), ctx.user_id
        )
    except ValueError as error:
        raise rejected("asa_assessment", str(error)) from error
    event_bus.publish_after_commit(
        db,
        EventType.PATIENT_MEDICAL_UPDATED,
        {"clinic_id": str(ctx.clinic_id), "patient_id": str(patient_id)},
    )
    return ApiResponse(data=(await _asa_responses(db, ctx.clinic_id, [assessment]))[0])


@router.post(
    "/patients/{patient_id}/asa/{assessment_id}/retract",
    response_model=ApiResponse[AsaAssessmentResponse],
)
async def retract_asa_assessment(
    patient_id: UUID,
    assessment_id: UUID,
    data: RetractRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.asa.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AsaAssessmentResponse]:
    """Take back an assessment recorded by mistake. It is not deleted, and
    the one before it becomes the current class again."""
    assessment = await PatientsClinicalService.get_asa_assessment(
        db, ctx.clinic_id, patient_id, assessment_id
    )
    if assessment is None:
        raise record_not_found("asa_assessment", "Assessment")
    await PatientsClinicalService.retract_entry(
        db, assessment, reason=data.reason, user_id=ctx.user_id
    )
    return ApiResponse(data=(await _asa_responses(db, ctx.clinic_id, [assessment]))[0])


# --- Health questionnaire ------------------------------------------------


@router.get(
    "/patients/{patient_id}/questionnaires",
    response_model=ApiResponse[list[HealthQuestionnaireResponse]],
)
async def list_questionnaires(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[HealthQuestionnaireResponse]]:
    """The questionnaires the patient answered, newest first."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    rows = await PatientsClinicalService.list_questionnaires(db, ctx.clinic_id, patient_id)
    return ApiResponse(data=[HealthQuestionnaireResponse.model_validate(r) for r in rows])


@router.post(
    "/patients/{patient_id}/questionnaires",
    response_model=ApiResponse[HealthQuestionnaireResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_questionnaire(
    patient_id: UUID,
    data: HealthQuestionnaireCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[HealthQuestionnaireResponse]:
    """Record what the patient declared, or file the sheet they filled in."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        questionnaire = await PatientsClinicalService.create_questionnaire(
            db, ctx.clinic_id, patient_id, data.model_dump(), ctx.user_id
        )
    except ValueError as error:
        raise rejected("questionnaire", str(error)) from error
    return ApiResponse(data=HealthQuestionnaireResponse.model_validate(questionnaire))


@router.post(
    "/patients/{patient_id}/questionnaires/{questionnaire_id}/retract",
    response_model=ApiResponse[HealthQuestionnaireResponse],
)
async def retract_questionnaire(
    patient_id: UUID,
    questionnaire_id: UUID,
    data: RetractRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[HealthQuestionnaireResponse]:
    """Take back a questionnaire recorded by mistake. It is not deleted."""
    questionnaire = await PatientsClinicalService.get_questionnaire(
        db, ctx.clinic_id, patient_id, questionnaire_id
    )
    if questionnaire is None:
        raise record_not_found("questionnaire", "Questionnaire")
    await PatientsClinicalService.retract_entry(
        db, questionnaire, reason=data.reason, user_id=ctx.user_id
    )
    return ApiResponse(data=HealthQuestionnaireResponse.model_validate(questionnaire))


@router.get("/patients/{patient_id}/questionnaire-form")
async def blank_questionnaire_form(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients_clinical.medical.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    locale: str = Query(default="es", pattern="^(es|en)$"),
    kind: str = Query(default="adult", pattern="^(adult|pediatric)$"),
) -> Response:
    """The questionnaire as a blank sheet, to fill in by hand and scan:
    the adult form, or the pediatric one a parent or guardian signs."""
    patient = await PatientService.get_patient(db, ctx.clinic_id, patient_id)
    if patient is None:
        raise record_not_found("patient", "Patient")
    directory = provider(ProfessionalDirectory)
    professional_id = (
        await directory.for_account(db, ctx.clinic_id, ctx.user_id) if directory else None
    )
    pdf = await render_blank_pdf(db, patient, professional_id, locale, kind)
    filename = "cuestionario_pediatrico.pdf" if kind == "pediatric" else "cuestionario_de_salud.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
