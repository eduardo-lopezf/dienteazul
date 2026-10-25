"""FastAPI router for odontogram module."""

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse, PaginatedApiResponse
from app.core.utils.clinic_time import clinic_date
from app.database import get_db
from app.modules.patients.models import Patient

from .constants import (
    CONDITION_COLORS,
    SURFACES,
    ToothCondition,
    age_in_years,
    dentition_for_age,
    is_valid_tooth_number,
)
from .errors import odontogram_error, treatment_service_error
from .schemas import (
    BulkUpdateRequest,
    DentitionResponse,
    DentitionUpdate,
    EruptionAgesUpdate,
    ExchangeRequest,
    ExchangeResponse,
    HistoricalOdontogramResponse,
    HistoricalToothRecordResponse,
    HistoricalTreatmentResponse,
    HistoryEntryWithUser,
    OdontogramResponse,
    TimelineDateEntry,
    TimelineResponse,
    ToothRecordResponse,
    ToothRecordUpdate,
    ToothRecordWithTreatmentsResponse,
    TreatmentCreate,
    TreatmentPerform,
    TreatmentResponse,
    TreatmentUpdate,
)
from .service import (
    UNSET,
    DentitionService,
    EruptionService,
    OdontogramService,
    TreatmentService,
    build_treatment_response,
)

router = APIRouter()


async def validate_patient_access(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> Patient:
    from sqlalchemy import select

    result = await db.execute(
        select(Patient).where(
            Patient.id == patient_id,
            Patient.clinic_id == clinic_id,
            Patient.status != "archived",
        )
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise odontogram_error("odontogram.patient.not_found")
    return patient


# ============================================================================
# Tooth record endpoints
# ============================================================================


@router.get(
    "/patients/{patient_id}/odontogram",
    response_model=ApiResponse[OdontogramResponse],
)
async def get_odontogram(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[OdontogramResponse]:
    patient = await validate_patient_access(db, ctx.clinic_id, patient_id)
    teeth = await OdontogramService.get_patient_odontogram(db, ctx.clinic_id, patient_id)
    treatments, _total = await TreatmentService.list_patient_treatments(
        db=db, clinic_id=ctx.clinic_id, patient_id=patient_id, page=1, page_size=500
    )
    age = _patient_age(patient, ctx)
    response = OdontogramResponse(
        patient_id=patient_id,
        teeth=[ToothRecordResponse.model_validate(t) for t in teeth],
        treatments=[
            TreatmentResponse.model_validate(build_treatment_response(t)) for t in treatments
        ],
        condition_colors=CONDITION_COLORS,
        available_conditions=[c.value for c in ToothCondition],
        surfaces=SURFACES,
        patient_age=age,
        dentition=await DentitionService.get(db, ctx.clinic_id, patient_id),
        suggested_dentition=dentition_for_age(age),
        eruption_ages=await EruptionService.ages(db, ctx.clinic_id),
    )
    return ApiResponse(data=response)


def _patient_age(patient: Patient, ctx: ClinicContext) -> int | None:
    """Completed years today, by the clinic's calendar."""
    today = clinic_date(datetime.now(UTC), ctx.clinic.timezone)
    return age_in_years(patient.date_of_birth, today)


@router.post(
    "/patients/{patient_id}/odontogram/exchange",
    response_model=ApiResponse[ExchangeResponse],
)
async def exchange_tooth(
    patient_id: UUID,
    data: ExchangeRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ExchangeResponse]:
    """A primary tooth fell out and its successor is coming through: the
    first is marked exfoliated, the second erupting (unless already in)."""
    await validate_patient_access(db, ctx.clinic_id, patient_id)
    try:
        primary, successor = await EruptionService.exchange(
            db, ctx.clinic_id, patient_id, data.primary_tooth, ctx.user_id
        )
    except ValueError as exc:
        raise odontogram_error(
            "odontogram.eruption.invalid_primary_tooth", detail=str(exc)
        ) from exc
    return ApiResponse(
        data=ExchangeResponse(
            primary=ToothRecordResponse.model_validate(primary),
            successor=ToothRecordResponse.model_validate(successor),
        )
    )


@router.get(
    "/settings/eruption-ages",
    response_model=ApiResponse[dict[str, dict[str, int]]],
)
async def get_eruption_ages(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict[str, dict[str, int]]]:
    """The clinic's eruption chronology (arch → position → age)."""
    return ApiResponse(data=await EruptionService.ages(db, ctx.clinic_id))


@router.put(
    "/settings/eruption-ages",
    response_model=ApiResponse[dict[str, dict[str, int]]],
)
async def set_eruption_ages(
    data: EruptionAgesUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict[str, dict[str, int]]]:
    """Set the clinic's eruption chronology; ``null`` restores the default."""
    return ApiResponse(data=await EruptionService.set_ages(db, ctx.clinic_id, data.ages))


@router.put(
    "/patients/{patient_id}/odontogram/dentition",
    response_model=ApiResponse[DentitionResponse],
)
async def set_dentition(
    patient_id: UUID,
    data: DentitionUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentitionResponse]:
    """Keep which dentition this patient's chart shows; ``auto`` follows the age."""
    patient = await validate_patient_access(db, ctx.clinic_id, patient_id)
    dentition = await DentitionService.set(db, ctx.clinic_id, patient_id, data.dentition)
    age = _patient_age(patient, ctx)
    return ApiResponse(
        data=DentitionResponse(
            dentition=dentition, patient_age=age, suggested_dentition=dentition_for_age(age)
        )
    )


@router.get(
    "/patients/{patient_id}/teeth/{tooth_number}",
    response_model=ApiResponse[ToothRecordResponse],
)
async def get_tooth(
    patient_id: UUID,
    tooth_number: int,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ToothRecordResponse]:
    await validate_patient_access(db, ctx.clinic_id, patient_id)
    if not is_valid_tooth_number(tooth_number):
        raise odontogram_error(
            "odontogram.tooth.invalid_number", detail=f"Invalid tooth number: {tooth_number}"
        )
    tooth = await OdontogramService.get_tooth_record(db, ctx.clinic_id, patient_id, tooth_number)
    if not tooth:
        raise odontogram_error(
            "odontogram.tooth.not_found",
            detail=f"Tooth {tooth_number} not found for this patient",
        )
    return ApiResponse(data=ToothRecordResponse.model_validate(tooth))


@router.put(
    "/patients/{patient_id}/teeth/{tooth_number}",
    response_model=ApiResponse[ToothRecordResponse],
)
async def create_or_update_tooth(
    patient_id: UUID,
    tooth_number: int,
    data: ToothRecordUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ToothRecordResponse]:
    await validate_patient_access(db, ctx.clinic_id, patient_id)
    if not is_valid_tooth_number(tooth_number):
        raise odontogram_error(
            "odontogram.tooth.invalid_number", detail=f"Invalid tooth number: {tooth_number}"
        )
    surface_updates = None
    if data.surface_updates:
        surface_updates = [u.model_dump() for u in data.surface_updates]
    tooth = await OdontogramService.create_or_update_tooth(
        db=db,
        clinic_id=ctx.clinic_id,
        patient_id=patient_id,
        tooth_number=tooth_number,
        user_id=ctx.user_id,
        general_condition=data.general_condition,
        surface_updates=surface_updates,
        notes=data.notes,
        is_displaced=data.is_displaced,
        is_rotated=data.is_rotated,
        displacement_notes=data.displacement_notes,
        eruption_status=(data.eruption_status.value if data.eruption_status else None)
        if "eruption_status" in data.model_fields_set
        else UNSET,
    )
    return ApiResponse(data=ToothRecordResponse.model_validate(tooth))


@router.patch(
    "/patients/{patient_id}/teeth/bulk",
    response_model=ApiResponse[list[ToothRecordResponse]],
)
async def bulk_update_teeth(
    patient_id: UUID,
    data: BulkUpdateRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[ToothRecordResponse]]:
    await validate_patient_access(db, ctx.clinic_id, patient_id)
    for u in data.updates:
        if not is_valid_tooth_number(u.tooth_number):
            raise odontogram_error(
                "odontogram.tooth.invalid_number",
                detail=f"Invalid tooth number: {u.tooth_number}",
            )
    updates = []
    for u in data.updates:
        d = {
            "tooth_number": u.tooth_number,
            "general_condition": u.general_condition,
            "notes": u.notes,
        }
        if u.surface_updates:
            d["surface_updates"] = [s.model_dump() for s in u.surface_updates]
        updates.append(d)
    teeth = await OdontogramService.bulk_update_teeth(
        db=db,
        clinic_id=ctx.clinic_id,
        patient_id=patient_id,
        user_id=ctx.user_id,
        updates=updates,
    )
    return ApiResponse(data=[ToothRecordResponse.model_validate(t) for t in teeth])


@router.patch(
    "/patients/{patient_id}/teeth/{tooth_number}",
    response_model=ApiResponse[ToothRecordResponse],
)
async def partial_update_tooth(
    patient_id: UUID,
    tooth_number: int,
    data: ToothRecordUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ToothRecordResponse]:
    return await create_or_update_tooth(patient_id, tooth_number, data, ctx, _, db)


@router.get(
    "/patients/{patient_id}/teeth/{tooth_number}/history",
    response_model=PaginatedApiResponse[HistoryEntryWithUser],
)
async def get_tooth_history(
    patient_id: UUID,
    tooth_number: int,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> PaginatedApiResponse[HistoryEntryWithUser]:
    await validate_patient_access(db, ctx.clinic_id, patient_id)
    if not is_valid_tooth_number(tooth_number):
        raise odontogram_error(
            "odontogram.tooth.invalid_number", detail=f"Invalid tooth number: {tooth_number}"
        )
    history, total = await OdontogramService.get_tooth_history(
        db, ctx.clinic_id, patient_id, tooth_number, page, page_size
    )
    items = []
    for h in history:
        item = HistoryEntryWithUser.model_validate(h)
        if h.user:
            item.changed_by_name = f"{h.user.first_name} {h.user.last_name}"
        items.append(item)
    return PaginatedApiResponse(data=items, total=total, page=page, page_size=page_size)


@router.get(
    "/patients/{patient_id}/history",
    response_model=PaginatedApiResponse[HistoryEntryWithUser],
)
async def get_patient_odontogram_history(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> PaginatedApiResponse[HistoryEntryWithUser]:
    await validate_patient_access(db, ctx.clinic_id, patient_id)
    history, total = await OdontogramService.get_patient_history(
        db, ctx.clinic_id, patient_id, page, page_size
    )
    items = []
    for h in history:
        item = HistoryEntryWithUser.model_validate(h)
        if h.user:
            item.changed_by_name = f"{h.user.first_name} {h.user.last_name}"
        items.append(item)
    return PaginatedApiResponse(data=items, total=total, page=page, page_size=page_size)


@router.get(
    "/patients/{patient_id}/odontogram/timeline",
    response_model=ApiResponse[TimelineResponse],
)
async def get_odontogram_timeline(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TimelineResponse]:
    await validate_patient_access(db, ctx.clinic_id, patient_id)
    dates = await OdontogramService.get_timeline_dates(db, ctx.clinic_id, patient_id)
    return ApiResponse(
        data=TimelineResponse(dates=[TimelineDateEntry(**d) for d in dates], total=len(dates))
    )


@router.get(
    "/patients/{patient_id}/odontogram/at",
    response_model=ApiResponse[HistoricalOdontogramResponse],
)
async def get_odontogram_at_date(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    target_date: date = Query(..., alias="date"),
) -> ApiResponse[HistoricalOdontogramResponse]:
    patient = await validate_patient_access(db, ctx.clinic_id, patient_id)
    historical = await OdontogramService.get_odontogram_at_date(
        db, ctx.clinic_id, patient_id, target_date
    )
    age_then = age_in_years(patient.date_of_birth, target_date)
    return ApiResponse(
        data=HistoricalOdontogramResponse(
            patient_id=str(patient_id),
            date=target_date,
            patient_age=age_then,
            suggested_dentition=dentition_for_age(age_then),
            teeth=[HistoricalToothRecordResponse.model_validate(t) for t in historical["teeth"]],
            treatments=[
                HistoricalTreatmentResponse.model_validate(t) for t in historical["treatments"]
            ],
            condition_colors=CONDITION_COLORS,
            available_conditions=[c.value for c in ToothCondition],
            surfaces=SURFACES,
        )
    )


# ============================================================================
# Treatment endpoints (single or multi-tooth, unified)
# ============================================================================


@router.post(
    "/patients/{patient_id}/treatments",
    response_model=ApiResponse[TreatmentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_treatment(
    patient_id: UUID,
    data: TreatmentCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.treatments.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentResponse]:
    """Create a Treatment.

    Tooth, multi-tooth (uniform and bridge), global_mouth and global_arch flows all
    go through this endpoint. `scope` is derived from tooth count when omitted for
    non-global treatments; globals must pass `scope` explicitly.
    """
    await validate_patient_access(db, ctx.clinic_id, patient_id)
    # Schema `validate_shape` always resolves `scope` (raising if ambiguous).
    assert data.scope is not None
    try:
        treatment = await TreatmentService.create(
            db=db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            user_id=ctx.user_id,
            catalog_item_id=data.catalog_item_id,
            clinical_type=data.clinical_type,
            tooth_numbers=data.tooth_numbers,
            teeth=data.teeth,
            common_surfaces=data.surfaces,
            status=data.status,
            notes=data.notes,
            budget_item_id=data.budget_item_id,
            source_module=data.source_module,
            scope=data.scope,
            arch=data.arch,
        )
    except ValueError as exc:
        raise treatment_service_error(exc) from exc
    return ApiResponse(data=TreatmentResponse.model_validate(build_treatment_response(treatment)))


@router.get(
    "/patients/{patient_id}/treatments",
    response_model=PaginatedApiResponse[TreatmentResponse],
)
async def list_patient_treatments(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.treatments.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = Query(default=None, alias="status"),
    clinical_type: str | None = Query(default=None),
    tooth_number: int | None = Query(default=None),
    catalog_item_id: UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> PaginatedApiResponse[TreatmentResponse]:
    await validate_patient_access(db, ctx.clinic_id, patient_id)
    treatments, total = await TreatmentService.list_patient_treatments(
        db=db,
        clinic_id=ctx.clinic_id,
        patient_id=patient_id,
        status=status_filter,
        clinical_type=clinical_type,
        tooth_number=tooth_number,
        catalog_item_id=catalog_item_id,
        page=page,
        page_size=page_size,
    )
    return PaginatedApiResponse(
        data=[TreatmentResponse.model_validate(build_treatment_response(t)) for t in treatments],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/treatments/{treatment_id}",
    response_model=ApiResponse[TreatmentResponse],
)
async def get_treatment(
    treatment_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.treatments.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentResponse]:
    treatment = await TreatmentService.get_treatment(db, ctx.clinic_id, treatment_id)
    if not treatment:
        raise odontogram_error("odontogram.treatment.not_found")
    return ApiResponse(data=TreatmentResponse.model_validate(build_treatment_response(treatment)))


@router.put(
    "/treatments/{treatment_id}",
    response_model=ApiResponse[TreatmentResponse],
)
async def update_treatment(
    treatment_id: UUID,
    data: TreatmentUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.treatments.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentResponse]:
    treatment = await TreatmentService.update(
        db=db,
        clinic_id=ctx.clinic_id,
        treatment_id=treatment_id,
        user_id=ctx.user_id,
        status=data.status,
        notes=data.notes,
        surfaces=data.surfaces,
    )
    if not treatment:
        raise odontogram_error("odontogram.treatment.not_found")
    return ApiResponse(data=TreatmentResponse.model_validate(build_treatment_response(treatment)))


@router.delete("/treatments/{treatment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_treatment(
    treatment_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.treatments.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    deleted = await TreatmentService.delete(db, ctx.clinic_id, treatment_id, ctx.user_id)
    if not deleted:
        raise odontogram_error("odontogram.treatment.not_found")


@router.patch(
    "/treatments/{treatment_id}/perform",
    response_model=ApiResponse[TreatmentResponse],
)
async def perform_treatment(
    treatment_id: UUID,
    data: TreatmentPerform,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.treatments.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentResponse]:
    treatment = await TreatmentService.perform(
        db=db,
        clinic_id=ctx.clinic_id,
        treatment_id=treatment_id,
        user_id=ctx.user_id,
        notes=data.notes,
    )
    if not treatment:
        raise odontogram_error("odontogram.treatment.not_found")
    return ApiResponse(data=TreatmentResponse.model_validate(build_treatment_response(treatment)))


@router.get(
    "/patients/{patient_id}/teeth/{tooth_number}/full",
    response_model=ApiResponse[ToothRecordWithTreatmentsResponse],
)
async def get_tooth_with_treatments(
    patient_id: UUID,
    tooth_number: int,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("odontogram.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ToothRecordWithTreatmentsResponse]:
    await validate_patient_access(db, ctx.clinic_id, patient_id)
    if not is_valid_tooth_number(tooth_number):
        raise odontogram_error(
            "odontogram.tooth.invalid_number", detail=f"Invalid tooth number: {tooth_number}"
        )
    tooth, treatments = await OdontogramService.get_tooth_with_treatments(
        db, ctx.clinic_id, patient_id, tooth_number
    )
    if not tooth:
        raise odontogram_error(
            "odontogram.tooth.not_found", detail=f"Tooth {tooth_number} not found"
        )
    response = ToothRecordWithTreatmentsResponse.model_validate(tooth)
    response.treatments = [
        TreatmentResponse.model_validate(build_treatment_response(t)) for t in treatments
    ]
    return ApiResponse(data=response)
