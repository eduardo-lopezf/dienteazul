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
from datetime import UTC, datetime
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
    Request,
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
from app.core.tenancy import TenantContext, get_tenant
from app.database import get_db

from .binaries.ingest import ingest_binary
from .errors import migration_error
from .export import ExportJobService
from .export import expires_at as export_expires_at
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
from .service import ImportJobService, ImportUndoService
from .sheets import KINDS, SheetError, missing_required, read_sheet, template_for
from .sheets import MAX_BYTES as SHEET_MAX_BYTES
from .sheets import SOURCE_SYSTEM as SHEET_SOURCE
from .sheets import SUFFIXES as SHEET_SUFFIXES
from .sheets.appointments import convert_appointments
from .sheets.balances import convert_balances
from .sheets.common import (
    column_kind,
    infer_date_order,
    region_of,
    sheet_hash,
    suggest,
    suggest_by_content,
)
from .sheets.identify import PatientMatcher
from .sheets.patients import convert_patients
from .sheets.report import problems_report
from .space import ensure_room, free_bytes

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
    request: Request,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
    _: Annotated[None, Depends(require_permission("migration_import.job.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ImportJobResponse]:
    """Stream the upload to disk and return a job row in ``uploaded``."""
    await ensure_room(
        db, tenant, ctx.clinic_id, _request_size(request), "subir este archivo de migración"
    )
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
                    raise migration_error(
                        "migration_import.upload.too_large",
                        detail=f"DPMF exceeds {_MAX_UPLOAD_BYTES} bytes",
                    )
                await out.write(chunk)
    except HTTPException:
        # 413 — clean up the partial file before re-raising.
        staged_path.unlink(missing_ok=True)
        raise
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise

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
    tenant: Annotated[TenantContext, Depends(get_tenant)],
    _: Annotated[None, Depends(require_permission("migration_import.job.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PreviewResponse]:
    job = await _get_job_or_404(db, ctx.clinic_id, job_id)
    try:
        preview = await ImportJobService.preview(db, job, passphrase=request.passphrase)
    except ValueError as exc:
        raise migration_error("migration_import.job.invalid_state", detail=str(exc)) from exc
    preview.storage_needed_bytes = job.expected_storage_bytes or 0
    preview.storage_free_bytes = await free_bytes(db, tenant, ctx.clinic_id)
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
    tenant: Annotated[TenantContext, Depends(get_tenant)],
    _: Annotated[None, Depends(require_permission("migration_import.job.execute"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ImportJobResponse]:
    job = await _get_job_or_404(db, ctx.clinic_id, job_id)
    if job.status not in {"validated", "previewing", "completed", "failed"}:
        raise migration_error(
            "migration_import.job.invalid_state",
            detail=f"cannot execute job in status {job.status}",
        )
    # The documents the file brings land in the clinic's storage.
    await ensure_room(
        db,
        tenant,
        ctx.clinic_id,
        job.expected_storage_bytes or 0,
        "importar los documentos de este archivo",
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
        raise migration_error("migration_import.proposal.invalid", detail=str(exc)) from exc
    if decision is None:
        raise migration_error("migration_import.proposal.not_found")
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
    request: Request,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
    _: Annotated[None, Depends(require_permission("migration_import.binary.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict]:
    job = await _get_job_or_404(db, ctx.clinic_id, job_id)
    # A file lands among the patient's documents; with them off there is
    # nowhere to put it.
    if not running("media"):
        raise migration_error("migration_import.binary.documents_unavailable")
    await ensure_room(db, tenant, ctx.clinic_id, _request_size(request), "guardar este documento")
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
    request: Request,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
    _: Annotated[None, Depends(require_permission("migration_import.job.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    kind: Annotated[SheetKind, Form()] = "patients",
) -> ApiResponse[SheetUploadResponse]:
    """Keep the sheet, read its columns, and suggest what each one is."""
    await ensure_room(db, tenant, ctx.clinic_id, _request_size(request), "subir esta hoja")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SHEET_SUFFIXES:
        raise migration_error("migration_import.sheet.unsupported_format")
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
                raise migration_error("migration_import.sheet.too_large")
            await out.write(chunk)
    try:
        sheet = read_sheet(staged_path)
    except SheetError as exc:
        staged_path.unlink(missing_ok=True)
        raise migration_error("migration_import.sheet.invalid_content", detail=str(exc)) from exc

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
    spec = KINDS[kind]
    region = region_of(await db.get(Clinic, ctx.clinic_id))
    by_name = suggest(sheet.headers, spec.fields)
    suggested = suggest_by_content(sheet.rows, by_name, spec.by_kind or {}, region)
    # The order of the dates, when the values give it away.
    date_values = [
        row[index]
        for index in range(len(sheet.headers))
        if column_kind([r[index] for r in sheet.rows[:200]], region) == "date"
        for row in sheet.rows
    ]
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
                    suggested_from=(
                        "name" if by_name[index] else "content" if suggested[index] else None
                    ),
                )
                for index, name in enumerate(sheet.headers)
            ],
            row_count=len(sheet.rows),
            fields=list(spec.fields),
            date_order=infer_date_order(date_values),
            headerless=sheet.headerless,
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
        raise migration_error("migration_import.sheet.already_converted")
    kind = (job.execute_options or {}).get("sheet_kind", "patients")
    spec = KINDS[kind]
    chosen = set(body.mapping.values())
    unknown = sorted(chosen - set(spec.fields))
    if unknown:
        raise migration_error(
            "migration_import.sheet.mapping_unknown_field",
            detail=f"Campos desconocidos: {', '.join(unknown)}.",
        )
    if len(chosen) != len(body.mapping):
        raise migration_error("migration_import.sheet.mapping_duplicate_field")
    missing = missing_required(kind, chosen)
    if missing:
        needed = ", ".join(sorted(spec.fields[field][0] for field in missing[0]))
        raise migration_error(
            "migration_import.sheet.mapping_required_field_missing",
            detail=f"Falta asignar una columna a alguno de estos datos: {needed}.",
        )
    # Patients are what appointments and balances attach to.
    if kind != "patients" and not running("patients"):
        raise migration_error("migration_import.sheet.patients_unavailable")

    sheet_path = Path(job.file_path)
    sheet = read_sheet(sheet_path)
    problems: list[tuple[str | None, str]] = []
    mapping = {int(index): field for index, field in body.mapping.items()}
    if any(index < 0 or index >= len(sheet.headers) for index in mapping):
        raise migration_error("migration_import.sheet.column_not_found")
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
        "problems": problems,
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
        # Who the clinic already has: a row that is one of them is not
        # created twice unless the person asked for it.
        existing = (
            await PatientMatcher.load(db, ctx.clinic_id, common["region"])
            if running("patients")
            else None
        )
        counts = convert_patients(**common, existing=existing, on_duplicate=body.on_duplicate)
    # The rows that did not go in whole, as a sheet to fix and upload again.
    report = problems_report(sheet, problems)
    report_path = _problems_report_path(sheet_path, job.id)
    report_path.unlink(missing_ok=True)
    if report is not None:
        report_path.write_bytes(report)
    sheet_path.unlink(missing_ok=True)
    job.file_path = str(destination)
    job.file_size = destination.stat().st_size
    job.total_entities = sum(counts.values())
    job.status = "uploaded"
    await db.flush()
    return ApiResponse(data=ImportJobResponse.model_validate(job))


def _problems_report_path(beside: Path, job_id: UUID) -> Path:
    return beside.with_name(f"{job_id}-filas-con-problemas.xlsx")


@router.get("/sheets/{job_id}/problems")
async def download_sheet_problems(
    job_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    """The rows of the sheet that did not go in whole, with why."""
    job = await _get_job_or_404(db, ctx.clinic_id, job_id)
    path = _problems_report_path(Path(job.file_path), job.id)
    if not path.exists():
        raise migration_error("migration_import.sheet.problems_not_found")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="filas-con-problemas.xlsx",
    )


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
    tenant: Annotated[TenantContext, Depends(get_tenant)],
    _: Annotated[None, Depends(require_permission("migration_import.export.run"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ExportJobResponse]:
    """Start writing the clinic to a file. The passphrase stays in memory.

    The file stays on the server until removed: it has to fit, beside the
    exports already kept there, in the clinic's storage."""
    await ensure_room(
        db,
        tenant,
        ctx.clinic_id,
        await ExportJobService.expected_bytes(db, ctx.clinic_id, body.include_documents),
        "generar la exportación (más las exportaciones que siguen guardadas)",
    )
    job = await ExportJobService.create(db, ctx.clinic_id, ctx.user_id)
    background_tasks.add_task(
        ExportJobService.run_in_background,
        job.id,
        passphrase=body.passphrase,
        include_documents=body.include_documents,
    )
    return ApiResponse(data=_export_view(job))


@router.get("/exports", response_model=ApiResponse[list[ExportJobResponse]])
async def list_exports(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.export.run"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[ExportJobResponse]]:
    jobs = await ExportJobService.list(db, ctx.clinic_id)
    return ApiResponse(data=[_export_view(job) for job in jobs])


@router.get("/exports/{export_id}", response_model=ApiResponse[ExportJobResponse])
async def get_export(
    export_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.export.run"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ExportJobResponse]:
    job = await _get_export_or_404(db, ctx.clinic_id, export_id)
    return ApiResponse(data=_export_view(job))


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.export.run"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    job = await _get_export_or_404(db, ctx.clinic_id, export_id)
    ends = export_expires_at(job)
    if ends is not None and ends <= datetime.now(UTC):
        raise migration_error("migration_import.export.expired")
    if job.status != "completed" or not job.file_path or not Path(job.file_path).exists():
        raise migration_error("migration_import.export.file_unavailable")
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
        raise migration_error("migration_import.export.in_progress")
    job = await ExportJobService.delete_file(db, job)
    return ApiResponse(data=_export_view(job))


def _export_view(job) -> ExportJobResponse:
    view = ExportJobResponse.model_validate(job)
    view.expires_at = export_expires_at(job)
    return view


async def _get_export_or_404(db: AsyncSession, clinic_id: UUID, export_id: UUID):
    job = await ExportJobService.get(db, clinic_id, export_id)
    if job is None:
        raise migration_error("migration_import.export.not_found")
    return job


# ---------------------------------------------------------------------------
# POST /jobs/{id}/undo — remove what an import created (ADR 0055)
# ---------------------------------------------------------------------------


@router.post(
    "/jobs/{job_id}/undo",
    response_model=ApiResponse[ImportJobResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def undo_job(
    job_id: UUID,
    background_tasks: BackgroundTasks,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("migration_import.job.execute"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ImportJobResponse]:
    """Refuse at once when the clinic worked on what was imported; else
    remove it in the background."""
    from .undo import describe_blockers

    job = await _get_job_or_404(db, ctx.clinic_id, job_id)
    try:
        plan = await ImportUndoService.check(db, job)
    except ValueError as exc:
        raise migration_error("migration_import.undo.invalid_state", detail=str(exc)) from exc
    if plan.blockers:
        raise migration_error(
            "migration_import.undo.blocked", detail=describe_blockers(plan)
        )
    job.execute_options = {**(job.execute_options or {}), "status_before_undo": job.status}
    job.status = "undoing"
    job.undo_error = None
    job.undo_error_code = None
    await db.flush()
    background_tasks.add_task(ImportUndoService.undo_in_background, job.id, ctx.user_id)
    return ApiResponse(data=ImportJobResponse.model_validate(job))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request_size(request: Request) -> int:
    """What an upload will take: its request's length stands for its file."""
    return int(request.headers.get("content-length") or 0)


async def _get_job_or_404(db: AsyncSession, clinic_id: UUID, job_id: UUID):
    job = await ImportJobService.get_job(db, clinic_id, job_id)
    if job is None:
        raise migration_error("migration_import.job.not_found")
    return job
