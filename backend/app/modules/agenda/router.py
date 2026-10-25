"""Agenda HTTP surface: appointments + cabinets.

Mounts at ``/api/v1/agenda/*``. Appointments use the
``agenda.appointments.*`` namespace; cabinets still gate on
``admin.clinic.write`` until Etapa B.2 chunk 3 normalizes cabinets
into their own table + permission namespace.
"""

from datetime import date as date_type
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse, PaginatedApiResponse
from app.database import get_db

from .errors import agenda_error, service_error
from .integrations import treatments_available
from .kanban_service import KanbanDayService
from .models import Appointment
from .presenter import present, present_one
from .schemas import (
    AppointmentCabinetAssignment,
    AppointmentCabinetEventResponse,
    AppointmentCompletionCheck,
    AppointmentCreate,
    AppointmentResponse,
    AppointmentStatusEventResponse,
    AppointmentStatusTransition,
    AppointmentTreatmentNoteUpdate,
    AppointmentTreatmentResponse,
    AppointmentUpdate,
    CabinetCreate,
    CabinetResponse,
    CabinetUpdate,
    KanbanDaySnapshot,
    PlanLackingConsent,
)
from .service import (
    AlreadyInStateError,
    AppointmentService,
    CabinetRequiredError,
    CabinetService,
    InvalidTransitionError,
)

router = APIRouter()


# --- Appointments -------------------------------------------------------


@router.get("/appointments", response_model=PaginatedApiResponse[AppointmentResponse])
async def list_appointments(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    cabinet: str | None = None,
    professional_id: UUID | None = None,
    patient_id: UUID | None = None,
    appointment_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> PaginatedApiResponse[AppointmentResponse]:
    """List appointments with filters."""
    appointments, total = await AppointmentService.list_appointments(
        db,
        ctx.clinic_id,
        start_date,
        end_date,
        cabinet,
        professional_id,
        appointment_status,
        page,
        page_size,
        patient_id=patient_id,
    )
    return PaginatedApiResponse(
        data=await present(db, ctx.clinic_id, appointments),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/appointments",
    response_model=ApiResponse[AppointmentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_appointment(
    data: AppointmentCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AppointmentResponse]:
    """Create a new appointment."""
    if data.patient_id:
        if not await AppointmentService.validate_patient_access(db, ctx.clinic_id, data.patient_id):
            raise agenda_error("agenda.patient.not_found")

    if data.professional_id and not await AppointmentService.validate_professional_access(
        db, ctx.clinic_id, data.professional_id
    ):
        raise agenda_error("agenda.professional.invalid")

    try:
        appointment = await AppointmentService.create_appointment(
            db,
            ctx.clinic_id,
            data.model_dump(exclude_unset=True),
            created_by=ctx.user_id,
        )
    except ValueError as e:
        raise service_error(e) from e
    except IntegrityError as e:
        raise agenda_error("agenda.appointment.slot_conflict") from e

    return ApiResponse(data=await present_one(db, appointment))


@router.get("/appointments/{appointment_id}", response_model=ApiResponse[AppointmentResponse])
async def get_appointment(
    appointment_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AppointmentResponse]:
    """Get an appointment by ID, including the status audit trail."""
    appointment = await AppointmentService.get_appointment(db, ctx.clinic_id, appointment_id)
    if not appointment:
        raise agenda_error("agenda.appointment.not_found")
    events = await AppointmentService.list_status_events(db, ctx.clinic_id, appointment.id)
    response = await present_one(db, appointment)
    response.history = [AppointmentStatusEventResponse.model_validate(e) for e in events]
    return ApiResponse(data=response)


@router.put("/appointments/{appointment_id}", response_model=ApiResponse[AppointmentResponse])
async def update_appointment(
    appointment_id: UUID,
    data: AppointmentUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AppointmentResponse]:
    """Update an appointment."""
    appointment = await AppointmentService.get_appointment(db, ctx.clinic_id, appointment_id)
    if not appointment:
        raise agenda_error("agenda.appointment.not_found")

    if data.patient_id:
        if not await AppointmentService.validate_patient_access(db, ctx.clinic_id, data.patient_id):
            raise agenda_error("agenda.patient.not_found")

    if data.professional_id:
        if not await AppointmentService.validate_professional_access(
            db, ctx.clinic_id, data.professional_id
        ):
            raise agenda_error("agenda.professional.invalid")

    try:
        appointment = await AppointmentService.update_appointment(
            db,
            appointment,
            data.model_dump(exclude_unset=True),
            changed_by=ctx.user_id,
        )
    except ValueError as e:
        raise service_error(e) from e
    except IntegrityError as e:
        raise agenda_error("agenda.appointment.slot_conflict") from e

    return ApiResponse(data=await present_one(db, appointment))


@router.delete("/appointments/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_appointment(
    appointment_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Cancel an appointment."""
    appointment = await AppointmentService.get_appointment(db, ctx.clinic_id, appointment_id)
    if not appointment:
        raise agenda_error("agenda.appointment.not_found")
    try:
        await AppointmentService.cancel_appointment(db, appointment, changed_by=ctx.user_id)
    except InvalidTransitionError as e:
        raise agenda_error("agenda.appointment.invalid_transition", detail=str(e)) from e
    except ValueError as e:
        raise service_error(e) from e


@router.post(
    "/appointments/{appointment_id}/transitions",
    response_model=ApiResponse[AppointmentResponse],
)
async def transition_appointment(
    appointment_id: UUID,
    data: AppointmentStatusTransition,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AppointmentResponse]:
    """Advance (or cancel) an appointment's status.

    Returns the full appointment with its ``history`` populated so the
    frontend can update the detail view in one round-trip.
    """
    appointment = await AppointmentService.get_appointment(db, ctx.clinic_id, appointment_id)
    if not appointment:
        raise agenda_error("agenda.appointment.not_found")
    try:
        await AppointmentService.transition(
            db, appointment, data.to_status, changed_by=ctx.user_id, note=data.note
        )
    except AlreadyInStateError as e:
        raise agenda_error("agenda.appointment.already_in_state", detail=str(e)) from e
    except CabinetRequiredError as e:
        raise agenda_error("agenda.appointment.cabinet_required", detail=str(e)) from e
    except InvalidTransitionError as e:
        raise agenda_error("agenda.appointment.invalid_transition", detail=str(e)) from e

    events = await AppointmentService.list_status_events(db, ctx.clinic_id, appointment.id)
    response = await present_one(db, appointment)
    response.history = [AppointmentStatusEventResponse.model_validate(e) for e in events]
    return ApiResponse(data=response)


@router.get(
    "/appointments/{appointment_id}/completion-check",
    response_model=ApiResponse[AppointmentCompletionCheck],
)
async def check_appointment_completion(
    appointment_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AppointmentCompletionCheck]:
    """What to ask before this visit is marked as completed.

    A notice, never a stop: the transition itself does not look at it.
    """
    appointment = await AppointmentService.get_appointment(db, ctx.clinic_id, appointment_id)
    if not appointment:
        raise agenda_error("agenda.appointment.not_found")
    lacking = await AppointmentService.plans_lacking_consent(db, appointment)
    return ApiResponse(
        data=AppointmentCompletionCheck(
            plans_lacking_consent=[
                PlanLackingConsent(plan_id=plan_id, plan_number=number)
                for plan_id, number in lacking
            ]
        )
    )


@router.get(
    "/appointments/{appointment_id}/transitions",
    response_model=ApiResponse[list[AppointmentStatusEventResponse]],
)
async def list_appointment_transitions(
    appointment_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[AppointmentStatusEventResponse]]:
    """Return the full status audit trail for an appointment (asc)."""
    appointment = await AppointmentService.get_appointment(db, ctx.clinic_id, appointment_id)
    if not appointment:
        raise agenda_error("agenda.appointment.not_found")
    events = await AppointmentService.list_status_events(db, ctx.clinic_id, appointment.id)
    return ApiResponse(data=[AppointmentStatusEventResponse.model_validate(e) for e in events])


@router.patch(
    "/appointments/{appointment_id}/cabinet",
    response_model=ApiResponse[AppointmentResponse],
)
async def assign_appointment_cabinet(
    appointment_id: UUID,
    data: AppointmentCabinetAssignment,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AppointmentResponse]:
    """Assign, reassign, or (with ``cabinet_id=null``) unassign a cabinet.

    Returns the updated appointment with its cabinet history populated so
    the frontend can update the detail view in one round-trip.
    """
    appointment = await AppointmentService.get_appointment(db, ctx.clinic_id, appointment_id)
    if not appointment:
        raise agenda_error("agenda.appointment.not_found")
    try:
        await AppointmentService.assign_cabinet(
            db,
            appointment,
            data.cabinet_id,
            changed_by=ctx.user_id,
            note=data.note,
        )
    except ValueError as e:
        raise service_error(e) from e
    except IntegrityError as e:
        raise agenda_error("agenda.appointment.slot_conflict") from e

    events = await AppointmentService.list_cabinet_events(db, ctx.clinic_id, appointment.id)
    response = await present_one(db, appointment)
    response.cabinet_history = [AppointmentCabinetEventResponse.model_validate(e) for e in events]
    return ApiResponse(data=response)


@router.get(
    "/appointments/{appointment_id}/cabinet-history",
    response_model=ApiResponse[list[AppointmentCabinetEventResponse]],
)
async def list_appointment_cabinet_history(
    appointment_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[AppointmentCabinetEventResponse]]:
    """Return the cabinet assignment audit trail (asc)."""
    appointment = await AppointmentService.get_appointment(db, ctx.clinic_id, appointment_id)
    if not appointment:
        raise agenda_error("agenda.appointment.not_found")
    events = await AppointmentService.list_cabinet_events(db, ctx.clinic_id, appointment.id)
    return ApiResponse(data=[AppointmentCabinetEventResponse.model_validate(e) for e in events])


# --- Kanban day snapshot (issue #51) -----------------------------------


@router.get(
    "/kanban/day",
    response_model=ApiResponse[KanbanDaySnapshot],
)
async def get_kanban_day(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    target: date_type | None = Query(
        default=None,
        alias="date",
        description="Day to snapshot (defaults to today, clinic UTC)",
    ),
) -> ApiResponse[KanbanDaySnapshot]:
    """Return the professionals strip state for the kanban board."""
    target_date = target or datetime.utcnow().date()
    data = await KanbanDayService.snapshot(db, ctx.clinic_id, target_date)
    return ApiResponse(data=KanbanDaySnapshot(**data))


# --- Cabinets (real table) ----------------------------------------------


@router.get("/cabinets", response_model=ApiResponse[list[CabinetResponse]])
async def list_cabinets(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.cabinets.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[CabinetResponse]]:
    """List cabinets in the current clinic."""
    cabinets = await CabinetService.list_cabinets(db, ctx.clinic_id)
    return ApiResponse(data=[CabinetResponse.model_validate(c) for c in cabinets])


@router.post(
    "/cabinets",
    response_model=ApiResponse[CabinetResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_cabinet(
    data: CabinetCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.cabinets.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CabinetResponse]:
    """Create a new cabinet in the clinic."""
    existing = await CabinetService.get_by_name(db, ctx.clinic_id, data.name)
    if existing is not None:
        raise agenda_error("agenda.cabinet.name_conflict")

    cabinet = await CabinetService.create_cabinet(
        db, ctx.clinic_id, data.model_dump(exclude_unset=True)
    )
    await db.commit()
    await db.refresh(cabinet)
    return ApiResponse(data=CabinetResponse.model_validate(cabinet))


@router.put("/cabinets/{cabinet_id}", response_model=ApiResponse[CabinetResponse])
async def update_cabinet(
    cabinet_id: UUID,
    data: CabinetUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.cabinets.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CabinetResponse]:
    """Update a cabinet."""
    cabinet = await CabinetService.get_cabinet(db, ctx.clinic_id, cabinet_id)
    if cabinet is None:
        raise agenda_error("agenda.cabinet.not_found")

    if data.name and data.name != cabinet.name:
        clash = await CabinetService.get_by_name(db, ctx.clinic_id, data.name)
        if clash is not None and clash.id != cabinet.id:
            raise agenda_error("agenda.cabinet.name_conflict")

    cabinet = await CabinetService.update_cabinet(db, cabinet, data.model_dump(exclude_unset=True))
    await db.commit()
    await db.refresh(cabinet)
    return ApiResponse(data=CabinetResponse.model_validate(cabinet))


@router.delete("/cabinets/{cabinet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cabinet(
    cabinet_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.cabinets.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a cabinet. Blocks when any non-cancelled appointment still uses it."""
    cabinet = await CabinetService.get_cabinet(db, ctx.clinic_id, cabinet_id)
    if cabinet is None:
        raise agenda_error("agenda.cabinet.not_found")

    from sqlalchemy import func as sql_func

    in_use = (
        await db.execute(
            select(sql_func.count())
            .select_from(Appointment)
            .where(
                Appointment.cabinet_id == cabinet.id,
                Appointment.status != "cancelled",
            )
        )
    ).scalar() or 0
    if in_use:
        raise agenda_error(
            "agenda.cabinet.in_use", detail=f"Cabinet has {in_use} active appointments"
        )

    await CabinetService.delete_cabinet(db, cabinet)
    await db.commit()


# --- Visit-level clinical note ------------------------------------------


@router.patch(
    "/appointment-treatments/{appointment_treatment_id}",
    response_model=ApiResponse[AppointmentTreatmentResponse],
)
async def update_appointment_treatment_note(
    appointment_treatment_id: UUID,
    data: AppointmentTreatmentNoteUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("clinical_notes.notes.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AppointmentTreatmentResponse]:
    """Update visit-level clinical note + completion flag on an AppointmentTreatment.

    Permission lives under ``clinical_notes.notes`` because conceptually this
    is the visit-level anchor of the four-level clinical-notes model even
    though the row is owned by the agenda module (issue #60).
    """
    if not treatments_available():
        raise agenda_error("agenda.treatments.unavailable")

    row = await AppointmentService.update_appointment_treatment_note(
        db,
        ctx.clinic_id,
        appointment_treatment_id,
        ctx.user_id,
        notes=data.notes,
        completed_in_appointment=data.completed_in_appointment,
    )
    if row is None:
        raise agenda_error("agenda.appointment_treatment.not_found")
    return ApiResponse(data=AppointmentTreatmentResponse.model_validate(row))
