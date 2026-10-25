"""Record endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .coverage import requirement_keys
from .disclosure import DisclosureError, DisclosureService
from .errors import record_error
from .format import SETTINGS_KEY, RecordFormat, read_format
from .schemas import (
    DisclosureCreate,
    DisclosureResponse,
    RecordFormatResponse,
    RecordResponse,
    RecordSectionOption,
)
from .service import RecordService

router = APIRouter()


@router.get("/patients/{patient_id}", response_model=ApiResponse[RecordResponse])
async def get_patient_record(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    include_retracted: bool = Query(
        default=False,
        description=(
            "Include entries that were taken back. They are never deleted, so "
            "'what did the chart say that day' stays answerable — but an entry "
            "that should not have existed is not part of what a colleague is "
            "handed, so asking for it is explicit."
        ),
    ),
) -> ApiResponse[RecordResponse]:
    """The patient's clinical record, composed from the installed modules.

    Not a table: every section comes from the module that owns that data, so
    the record cannot drift from the source. A module that holds nothing about
    this patient still returns its section, empty — "nothing here" is an
    answer, a missing section is not.
    """
    record = await RecordService.compose(
        db, ctx.clinic_id, patient_id, include_retracted=include_retracted
    )
    if record is None:
        raise record_error("record.patient.not_found")
    return ApiResponse(data=RecordResponse.model_validate(record))


# --- Disclosures --------------------------------------------------------------


@router.post(
    "/patients/{patient_id}/disclosures",
    response_model=ApiResponse[DisclosureResponse],
    status_code=201,
)
async def disclose_patient_record(
    patient_id: UUID,
    data: DisclosureCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("record.disclose"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DisclosureResponse]:
    """Produce the record as a document, and record that it was handed over.

    The only way a printable record comes to exist (ADR 0033): the
    document is stored exactly as it left, with its digest, and the
    disclosure becomes an entry of the patient's record.
    """
    try:
        disclosure = await DisclosureService.disclose(
            db, ctx.clinic_id, patient_id, ctx.user_id, data.model_dump()
        )
    except DisclosureError as error:
        raise record_error("record.disclosure.invalid", detail=str(error)) from error
    if disclosure is None:
        raise record_error("record.patient.not_found")
    return ApiResponse(data=DisclosureResponse.model_validate(disclosure))


@router.get(
    "/patients/{patient_id}/disclosures", response_model=ApiResponse[list[DisclosureResponse]]
)
async def list_patient_disclosures(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[DisclosureResponse]]:
    """Every time this patient's record was handed over, newest first."""
    rows = await DisclosureService.list_for_patient(db, ctx.clinic_id, patient_id)
    return ApiResponse(data=[DisclosureResponse.model_validate(row) for row in rows])


@router.get("/disclosures/{disclosure_id}/document")
async def disclosure_document(
    disclosure_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("record.disclose"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """The document exactly as it left — stored, never regenerated."""
    disclosure = await DisclosureService.get(db, ctx.clinic_id, disclosure_id, with_document=True)
    if disclosure is None:
        raise record_error("record.disclosure.not_found")
    return Response(
        content=disclosure.document,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="expediente_{disclosure.id.hex[:8]}.pdf"',
            "X-Document-SHA256": disclosure.document_sha256,
        },
    )


# --- Format -------------------------------------------------------------------


def _format_response(fmt: RecordFormat) -> RecordFormatResponse:
    return RecordFormatResponse(
        **fmt.model_dump(),
        available_sections=[
            RecordSectionOption(
                qualified_name=f"{module}.{section.name}",
                title_key=section.title_key,
                category=section.category,
            )
            for module, section in RecordService.catalogue()
        ],
        requirements=requirement_keys(),
    )


@router.get("/format", response_model=ApiResponse[RecordFormatResponse])
async def get_record_format(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("record.read"))],
) -> ApiResponse[RecordFormatResponse]:
    """How this clinic lays its record out, and what there is to lay out."""
    return ApiResponse(data=_format_response(read_format(ctx.clinic.settings)))


@router.put("/format", response_model=ApiResponse[RecordFormatResponse])
async def update_record_format(
    data: RecordFormat,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("record.configure"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RecordFormatResponse]:
    """Replace the clinic's record layout. An empty format is the default:
    every section, in the order of a paper *expediente*, every point
    checked. Hiding a section deletes nothing."""
    clinic = ctx.clinic
    clinic.settings = {
        **(clinic.settings or {}),
        SETTINGS_KEY: {
            key: list(dict.fromkeys(values)) for key, values in data.model_dump().items()
        },
    }
    await db.flush()
    return ApiResponse(data=_format_response(read_format(clinic.settings)))
