"""FastAPI router for the migration_import module.

Eight endpoints behind ``/api/v1/migration_import/``:

- ``POST   /jobs``                  upload, returns the ImportJob row
- ``POST   /jobs/{id}/validate``    decrypt/decompress/verify hash
- ``POST   /jobs/{id}/preview``     entity counts + samples + warnings
- ``POST   /jobs/{id}/execute``     run mappers as a BackgroundTask
- ``GET    /jobs``                  paginated list for the current clinic
- ``GET    /jobs/{id}``             detail (with progress)
- ``GET    /jobs/{id}/warnings``    paginated warnings
- ``POST   /jobs/{id}/binaries``    sync-agent receiver
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

import aiofiles
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.dependencies import (
    ClinicContext,
    get_clinic_context,
    require_permission,
)
from app.core.auth.models import Clinic
from app.core.contracts import ProfessionalDirectory, provider
from app.core.schemas import ApiResponse, PaginatedApiResponse
from app.database import get_db

from .binaries.ingest import ingest_binary
from .export import ExportJobService
from .lifecycle import _staging_root
from .mappers import running
from .proposals import ProposalsService
from .schemas import (
    BulkAcceptRequest,
    BulkAcceptResponse,
    ExecuteRequest,
    ExportCreate,
    ExportJobResponse,
    ImportJobResponse,
    MappingDecisionPatch,
    MappingDecisionResponse,
    PreviewResponse,
    ProposalsBuildResponse,
    SheetColumn,
    SheetConvertRequest,
    SheetProfessional,
    SheetUploadResponse,
    ValidateRequest,
    WarningResponse,
)
from .service import ImportJobService
from .sheets import KINDS, SheetError, missing_required, read_sheet, template_for
from .sheets import MAX_BYTES as SHEET_MAX_BYTES
from .sheets import SOURCE_SYSTEM as SHEET_SOURCE
from .sheets import SUFFIXES as SHEET_SUFFIXES
from .sheets.appointments import convert_appointments
from .sheets.balances import convert_balances
from .sheets.common import region_of, sheet_hash, suggest
from .sheets.patients import convert_patients

logger = logging.getLogger(__name__)

router = APIRouter()

# Default 5 GB cap on a DPMF upload. The actual binaries (radiographs,
# PDFs) come through ``/binaries`` one file at a time, so the .dpm file
# itself stays well under this in practice. Configurable via env.
_MAX_UPLOAD_BYTES = getattr(settings, "MIGRATION_MAX_DPMF_BYTES", 5 * 1024 * 1024 * 1024)
_UPLOAD_CHUNK = 1 << 20  # 1 MiB chunks to keep memory bounded


# ---------------------------------------------------------------------------
# POST /jobs — upload a DPMF file
# ---------------------------------------------------------------------------


@router.post(
    "/jobs",
    response_model=ApiResponse[ImportJobResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_job(
    file: Annotated[UploadFile, File()],
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ImportJobResponse]:
    """Stream the upload to disk and return a job row in ``uploaded``."""
    job_id = uuid.uuid4()
    staging_dir = _staging_root() / str(ctx.clinic_id)
    staging_dir.mkdir(parents=True, exist_ok=True)
    extension = Path(file.filename or "dpmf").suffix or ".dpm"
    staged_path = staging_dir / f"{job_id}{extension}"

    written = 0
    try:
        async with aiofiles.open(staged_path, "wb") as out:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > _MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"DPMF exceeds {_MAX_UPLOAD_BYTES} bytes",
                    )
                await out.write(chunk)
    except HTTPException:
        # 413 — clean up the partial file before re-raising.
        staged_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        staged_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed to stage upload: {exc}",
        ) from exc

    job = await ImportJobService.create_job(
        db,
        clinic_id=ctx.clinic_id,
        user_id=ctx.user_id,
        original_filename=file.filename or staged_path.name,
        staged_path=staged_path,
        file_size=written,
    )
    return ApiResponse(data=ImportJobResponse.model_validate(job))


# ---------------------------------------------------------------------------
# POST /jobs/{id}/validate
# ---------------------------------------------------------------------------


@router.post(
    "/jobs/{job_id}/validate",
    response_model=ApiResponse[ImportJobResponse],
)
async def validate_job(
    job_id: UUID,
    request: ValidateRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ImportJobResponse]:
    job = await _get_job_or_404(db, ctx.clinic_id, job_id)
    job = await ImportJobService.validate(db, job, passphrase=request.passphrase)
    return ApiResponse(data=ImportJobResponse.model_validate(job))


# ---------------------------------------------------------------------------
# POST /jobs/{id}/preview
# ---------------------------------------------------------------------------


@router.post(
    "/jobs/{job_id}/preview",
    response_model=ApiResponse[PreviewResponse],
)
async def preview_job(
    job_id: UUID,
    request: ValidateRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PreviewResponse]:
    job = await _get_job_or_404(db, ctx.clinic_id, job_id)
    try:
        preview = await ImportJobService.preview(db, job, passphrase=request.passphrase)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=preview)


# ---------------------------------------------------------------------------
# POST /jobs/{id}/execute
# ---------------------------------------------------------------------------


@router.post(
    "/jobs/{job_id}/execute",
    response_model=ApiResponse[ImportJobResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_job(
    job_id: UUID,
    request: ExecuteRequest,
    background_tasks: BackgroundTasks,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.execute"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ImportJobResponse]:
    job = await _get_job_or_404(db, ctx.clinic_id, job_id)
    if job.status not in {"validated", "previewing", "completed", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot execute job in status {job.status}",
        )
    background_tasks.add_task(
        ImportJobService.execute_in_background,
        job.id,
        ctx.clinic_id,
        passphrase=request.passphrase,
        import_fiscal_compliance=request.import_fiscal_compliance,
        execute_options=request.model_dump(
            exclude={"import_fiscal_compliance", "passphrase"},
        ),
    )
    return ApiResponse(data=ImportJobResponse.model_validate(job))


# ---------------------------------------------------------------------------
# GET /jobs (list)
# ---------------------------------------------------------------------------


@router.get(
    "/jobs",
    response_model=PaginatedApiResponse[ImportJobResponse],
)
async def list_jobs(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginatedApiResponse[ImportJobResponse]:
    items, total = await ImportJobService.list_jobs(db, ctx.clinic_id, page, page_size)
    return PaginatedApiResponse(
        data=[ImportJobResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /jobs/{id}
# ---------------------------------------------------------------------------


@router.get(
    "/jobs/{job_id}",
    response_model=ApiResponse[ImportJobResponse],
)
async def get_job(
    job_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ImportJobResponse]:
    job = await _get_job_or_404(db, ctx.clinic_id, job_id)
    return ApiResponse(data=ImportJobResponse.model_validate(job))


# ---------------------------------------------------------------------------
# GET /jobs/{id}/warnings
# ---------------------------------------------------------------------------


@router.get(
    "/jobs/{job_id}/warnings",
    response_model=PaginatedApiResponse[WarningResponse],
)
async def list_warnings(
    job_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    severity: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> PaginatedApiResponse[WarningResponse]:
    # Implicit auth check — confirm job belongs to the caller's clinic.
    await _get_job_or_404(db, ctx.clinic_id, job_id)
    items, total = await ImportJobService.list_warnings(
        db, job_id, page, page_size, severity=severity, entity_type=entity_type
    )
    return PaginatedApiResponse(
        data=[WarningResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Proposals — operator review of catalog mappings before execute
# ---------------------------------------------------------------------------


@router.post(
    "/jobs/{job_id}/proposals",
    response_model=ApiResponse[ProposalsBuildResponse],
)
async def build_proposals(
    job_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.execute"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: ValidateRequest | None = None,
) -> ApiResponse[ProposalsBuildResponse]:
    """Run the catalog mapper in dry-run mode, persisting one
    :class:`MappingDecision` per Gesdén ``treatment_catalog_item``.
    Idempotent: re-calling skips rows already proposed and returns the
    full tally.
    """
    job = await _get_job_or_404(db, ctx.clinic_id, job_id)
    counts = await ProposalsService.build_proposals(
        db, job, passphrase=(payload.passphrase if payload else None)
    )
    summary = ProposalsBuildResponse(
        total=sum(counts.values()),
        link=counts.get("link", 0),
        fuzzy_link=counts.get("fuzzy_link", 0),
        create=counts.get("create", 0),
    )
    return ApiResponse(data=summary)


@router.get(
    "/jobs/{job_id}/proposals",
    response_model=PaginatedApiResponse[MappingDecisionResponse],
)
async def list_proposals(
    job_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    operator_action: str | None = Query(default=None),
    proposed_action: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> PaginatedApiResponse[MappingDecisionResponse]:
    await _get_job_or_404(db, ctx.clinic_id, job_id)
    items, total = await ProposalsService.list_proposals(
        db,
        job_id,
        page=page,
        page_size=page_size,
        operator_action=operator_action,
        proposed_action=proposed_action,
    )
    return PaginatedApiResponse(
        data=[MappingDecisionResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/jobs/{job_id}/proposals/{canonical_uuid}",
    response_model=ApiResponse[MappingDecisionResponse],
)
async def patch_proposal(
    job_id: UUID,
    canonical_uuid: str,
    patch: MappingDecisionPatch,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.execute"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[MappingDecisionResponse]:
    await _get_job_or_404(db, ctx.clinic_id, job_id)
    try:
        decision = await ProposalsService.update_decision(
            db,
            job_id,
            canonical_uuid,
            operator_action=patch.operator_action,
            operator_target_id=patch.operator_target_id,
            operator_target_category_key=patch.operator_target_category_key,
            operator_notes=patch.operator_notes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="proposal not found")
    return ApiResponse(data=MappingDecisionResponse.model_validate(decision))


@router.post(
    "/jobs/{job_id}/proposals/bulk_accept",
    response_model=ApiResponse[BulkAcceptResponse],
)
async def bulk_accept_proposals(
    job_id: UUID,
    body: BulkAcceptRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.execute"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[BulkAcceptResponse]:
    await _get_job_or_404(db, ctx.clinic_id, job_id)
    accepted = await ProposalsService.bulk_accept(
        db, job_id, min_score=body.min_score, include_exact=body.include_exact
    )
    return ApiResponse(data=BulkAcceptResponse(accepted=accepted))


# ---------------------------------------------------------------------------
# POST /jobs/{id}/binaries — sync agent uploads a single binary
# ---------------------------------------------------------------------------


@router.post(
    "/jobs/{job_id}/binaries",
    response_model=ApiResponse[dict],
    status_code=status.HTTP_201_CREATED,
)
async def upload_binary(
    job_id: UUID,
    file: Annotated[UploadFile, File()],
    sha256: Annotated[str, Form()],
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.binary.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict]:
    job = await _get_job_or_404(db, ctx.clinic_id, job_id)
    # A file lands among the patient's documents; with them off there is
    # nowhere to put it.
    if not running("media"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Documents are not available — the file cannot be filed",
        )
    result = await ingest_binary(db, job=job, file=file, claimed_sha256=sha256)
    return ApiResponse(data=result)


# ---------------------------------------------------------------------------
# Sheets — patients, appointments or balances from Excel or CSV, turned
# into a .dpm job
# ---------------------------------------------------------------------------

SheetKind = Literal["patients", "appointments", "balances"]


@router.get("/sheets/template")
async def sheet_template(
    _: Annotated[None, Depends(require_permission("migration_import.job.write"))],
    kind: SheetKind = Query(default="patients"),
) -> Response:
    """The ``.xlsx`` with the columns this kind of sheet is recognised by."""
    return Response(
        content=template_for(kind),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="plantilla-{kind}.xlsx"'},
    )


@router.post(
    "/sheets",
    response_model=ApiResponse[SheetUploadResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_sheet(
    file: Annotated[UploadFile, File()],
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    kind: Annotated[SheetKind, Form()] = "patients",
) -> ApiResponse[SheetUploadResponse]:
    """Keep the sheet, read its columns, and suggest what each one is."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SHEET_SUFFIXES:
        raise HTTPException(status_code=422, detail="Only .xlsx and .csv files are accepted")
    job_id = uuid.uuid4()
    staging_dir = _staging_root() / str(ctx.clinic_id)
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_path = staging_dir / f"{job_id}{suffix}"
    written = 0
    async with aiofiles.open(staged_path, "wb") as out:
        while chunk := await file.read(_UPLOAD_CHUNK):
            written += len(chunk)
            if written > SHEET_MAX_BYTES:
                await out.close()
                staged_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="The file is larger than 20 MB",
                )
            await out.write(chunk)
    try:
        sheet = read_sheet(staged_path)
    except SheetError as exc:
        staged_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = await ImportJobService.create_job(
        db,
        clinic_id=ctx.clinic_id,
        user_id=ctx.user_id,
        original_filename=file.filename or staged_path.name,
        staged_path=staged_path,
        file_size=written,
    )
    job.status = "mapping"
    job.source_system = SHEET_SOURCE
    # Kept until the sheet is converted; the execute step rewrites it.
    job.execute_options = {"sheet_kind": kind}
    await db.flush()
    fields = KINDS[kind].fields
    suggested = suggest(sheet.headers, fields)
    return ApiResponse(
        data=SheetUploadResponse(
            job=ImportJobResponse.model_validate(job),
            kind=kind,
            columns=[
                SheetColumn(
                    index=index,
                    name=name,
                    samples=[row[index] for row in sheet.rows[:5]],
                    suggested_field=suggested[index],
                )
                for index, name in enumerate(sheet.headers)
            ],
            row_count=len(sheet.rows),
            fields=list(fields),
            professionals=await _bookable_professionals(db, ctx.clinic_id)
            if kind == "appointments"
            else [],
        )
    )


async def _bookable_professionals(db: AsyncSession, clinic_id: UUID) -> list[SheetProfessional]:
    """Who a row without a professional can be booked with, when they are kept."""
    directory = provider(ProfessionalDirectory)
    if directory is None:
        return []
    return [
        SheetProfessional(id=person.id, name=f"{person.first_name} {person.last_name}".strip())
        for person in await directory.list_bookable(db, clinic_id)
    ]


@router.post("/sheets/{job_id}/convert", response_model=ApiResponse[ImportJobResponse])
async def convert_sheet(
    job_id: UUID,
    body: SheetConvertRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ImportJobResponse]:
    """Turn the sheet into a ``.dpm``; the job then goes on as any other."""
    job = await _get_job_or_404(db, ctx.clinic_id, job_id)
    if job.status != "mapping":
        raise HTTPException(status_code=409, detail=f"cannot convert a job in status {job.status}")
    kind = (job.execute_options or {}).get("sheet_kind", "patients")
    spec = KINDS[kind]
    chosen = set(body.mapping.values())
    unknown = sorted(chosen - set(spec.fields))
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown fields: {', '.join(unknown)}")
    if len(chosen) != len(body.mapping):
        raise HTTPException(status_code=422, detail="a field is assigned to more than one column")
    missing = missing_required(kind, chosen)
    if missing:
        needed = " / ".join(sorted(missing[0]))
        raise HTTPException(status_code=422, detail=f"assign a column to one of: {needed}")
    # Patients are what appointments and balances attach to.
    if kind != "patients" and not running("patients"):
        raise HTTPException(status_code=409, detail="the Patients App is not enabled")

    sheet_path = Path(job.file_path)
    sheet = read_sheet(sheet_path)
    mapping = {int(index): field for index, field in body.mapping.items()}
    if any(index < 0 or index >= len(sheet.headers) for index in mapping):
        raise HTTPException(status_code=422, detail="a column does not exist in the sheet")
    clinic = await db.get(Clinic, ctx.clinic_id)
    destination = sheet_path.with_suffix(".dpm")
    destination.unlink(missing_ok=True)
    common = {
        "sheet": sheet,
        "mapping": mapping,
        "date_order": body.date_order,
        "region": region_of(clinic),
        "digest": sheet_hash(sheet_path),
        "destination": destination,
        "label": job.original_filename,
    }
    if kind == "appointments":
        counts = await convert_appointments(
            db,
            clinic_id=ctx.clinic_id,
            job_id=job.id,
            default_professional_id=body.default_professional_id,
            **common,
        )
    elif kind == "balances":
        counts = await convert_balances(db, clinic_id=ctx.clinic_id, job_id=job.id, **common)
    else:
        counts = convert_patients(**common)
    sheet_path.unlink(missing_ok=True)
    job.file_path = str(destination)
    job.file_size = destination.stat().st_size
    job.total_entities = sum(counts.values())
    job.status = "uploaded"
    await db.flush()
    return ApiResponse(data=ImportJobResponse.model_validate(job))


# ---------------------------------------------------------------------------
# Exports — the clinic written out to a sealed ``.dpm`` file
# ---------------------------------------------------------------------------


@router.post(
    "/exports",
    response_model=ApiResponse[ExportJobResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_export(
    body: ExportCreate,
    background_tasks: BackgroundTasks,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.export.run"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ExportJobResponse]:
    """Start writing the clinic to a file. The passphrase stays in memory."""
    job = await ExportJobService.create(db, ctx.clinic_id, ctx.user_id)
    background_tasks.add_task(
        ExportJobService.run_in_background,
        job.id,
        passphrase=body.passphrase,
        include_documents=body.include_documents,
    )
    return ApiResponse(data=ExportJobResponse.model_validate(job))


@router.get("/exports", response_model=ApiResponse[list[ExportJobResponse]])
async def list_exports(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.export.run"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[ExportJobResponse]]:
    jobs = await ExportJobService.list(db, ctx.clinic_id)
    return ApiResponse(data=[ExportJobResponse.model_validate(job) for job in jobs])


@router.get("/exports/{export_id}", response_model=ApiResponse[ExportJobResponse])
async def get_export(
    export_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.export.run"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ExportJobResponse]:
    job = await _get_export_or_404(db, ctx.clinic_id, export_id)
    return ApiResponse(data=ExportJobResponse.model_validate(job))


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.export.run"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    job = await _get_export_or_404(db, ctx.clinic_id, export_id)
    if job.status != "completed" or not job.file_path or not Path(job.file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="export file not available"
        )
    stamp = (job.completed_at or job.created_at).strftime("%Y%m%d-%H%M")
    return FileResponse(
        job.file_path,
        media_type="application/octet-stream",
        filename=f"dienteazul-{stamp}.dpm",
    )


@router.delete("/exports/{export_id}/file", response_model=ApiResponse[ExportJobResponse])
async def delete_export_file(
    export_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.export.run"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ExportJobResponse]:
    """Remove the file from the server. The record that it was made stays."""
    job = await _get_export_or_404(db, ctx.clinic_id, export_id)
    if job.status in {"pending", "running"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="export still running")
    job = await ExportJobService.delete_file(db, job)
    return ApiResponse(data=ExportJobResponse.model_validate(job))


async def _get_export_or_404(db: AsyncSession, clinic_id: UUID, export_id: UUID):
    job = await ExportJobService.get(db, clinic_id, export_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="export not found")
    return job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_job_or_404(db: AsyncSession, clinic_id: UUID, job_id: UUID):
    job = await ImportJobService.get_job(db, clinic_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return job
