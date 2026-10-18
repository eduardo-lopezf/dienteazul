"""HTTP endpoints for the clinic professional directory."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.auth.limits import require_storage_room
from app.core.schemas import ApiResponse, PaginatedApiResponse
from app.database import get_db

# Declared dependency (see manifest: depends=["media"]) — reuses the
# storage abstraction and validation helpers, not the patient-scoped
# Document model. No Document row is created for professional photos.
from app.modules.media.storage import get_storage_backend
from app.modules.media.validation import validate_file_size, validate_mime_type

from .models import Professional
from .schemas import (
    MyProfessionalUpdate,
    ProfessionalCreate,
    ProfessionalResponse,
    ProfessionalUpdate,
    ProfessionalWorkloadResponse,
)
from .service import (
    ProfessionalService,
    UnknownSpecialtyError,
    UnknownUserLinkError,
    UserLinkTakenError,
    WorkloadService,
)

router = APIRouter()


async def _to_response(
    db: AsyncSession, clinic_id: UUID, professional: Professional
) -> ProfessionalResponse:
    accessible = await ProfessionalService.emails_with_system_access(
        db, clinic_id, [professional.email]
    )
    has_access = bool(professional.email) and professional.email.lower() in accessible
    return ProfessionalResponse.model_validate(professional).model_copy(
        update={"has_system_access": has_access}
    )


async def _to_response_list(
    db: AsyncSession, clinic_id: UUID, professionals: list[Professional]
) -> list[ProfessionalResponse]:
    accessible = await ProfessionalService.emails_with_system_access(
        db, clinic_id, [p.email for p in professionals]
    )
    return [
        ProfessionalResponse.model_validate(p).model_copy(
            update={"has_system_access": bool(p.email) and p.email.lower() in accessible}
        )
        for p in professionals
    ]


@router.get("", response_model=PaginatedApiResponse[ProfessionalResponse])
async def list_professionals(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("professionals.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = None,
    professional_type: str | None = Query(
        default=None, pattern="^(dentist|hygienist|collaborator)$"
    ),
    include_inactive: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginatedApiResponse[ProfessionalResponse]:
    professionals, total = await ProfessionalService.list(
        db,
        ctx.clinic_id,
        search=search,
        professional_type=professional_type,
        include_inactive=include_inactive,
        page=page,
        page_size=page_size,
    )
    return PaginatedApiResponse(
        data=await _to_response_list(db, ctx.clinic_id, professionals),
        total=total,
        page=page,
        page_size=page_size,
    )


# Literal paths before `/{professional_id}`: FastAPI resolves in
# registration order and "me" would be parsed as an id.


@router.get("/me", response_model=ApiResponse[ProfessionalResponse])
async def get_my_profile(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ProfessionalResponse]:
    """The caller's own profile in this clinic — the one linked to their
    account. 404 for an account that is no professional here."""
    professional = await _my_profile(db, ctx)
    return ApiResponse(data=await _to_response(db, ctx.clinic_id, professional))


@router.put("/me", response_model=ApiResponse[ProfessionalResponse])
async def update_my_profile(
    data: MyProfessionalUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ProfessionalResponse]:
    """A professional keeps their own data: name, licence, specialties,
    contact. Nothing else — who the profile is stays the clinic's call."""
    professional = await _my_profile(db, ctx)
    try:
        updated = await ProfessionalService.update(
            db, professional, data.model_dump(exclude_unset=True)
        )
    except UnknownSpecialtyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=await _to_response(db, ctx.clinic_id, updated))


@router.get("/workload", response_model=ApiResponse[list[ProfessionalWorkloadResponse]])
async def list_workload(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("professionals.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    professional_id: Annotated[list[UUID] | None, Query()] = None,
) -> ApiResponse[list[ProfessionalWorkloadResponse]]:
    """What is assigned to each professional: patients seen, appointments,
    plans and treatments, as told by the Apps that are running. The
    clinic's active professionals unless ``professional_id`` names some."""
    rows = await WorkloadService.for_clinic(db, ctx.clinic_id, professional_id)
    return ApiResponse(
        data=[
            ProfessionalWorkloadResponse(professional_id=pid, patients=patients, counts=counts)
            for pid, patients, counts in rows
        ]
    )


async def _my_profile(db: AsyncSession, ctx: ClinicContext) -> Professional:
    professional_id = await ProfessionalService.for_user(db, ctx.clinic_id, ctx.user_id)
    professional = (
        await ProfessionalService.get(db, ctx.clinic_id, professional_id)
        if professional_id
        else None
    )
    if professional is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This account has no professional profile in this clinic",
        )
    return professional


@router.get("/{professional_id}", response_model=ApiResponse[ProfessionalResponse])
async def get_professional(
    professional_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("professionals.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ProfessionalResponse]:
    professional = await ProfessionalService.get(db, ctx.clinic_id, professional_id)
    if professional is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Professional not found")
    return ApiResponse(data=await _to_response(db, ctx.clinic_id, professional))


@router.post(
    "", response_model=ApiResponse[ProfessionalResponse], status_code=status.HTTP_201_CREATED
)
async def create_professional(
    data: ProfessionalCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("professionals.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ProfessionalResponse]:
    try:
        professional = await ProfessionalService.create(db, ctx.clinic_id, data.model_dump())
    except UnknownSpecialtyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except UnknownUserLinkError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except UserLinkTakenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=await _to_response(db, ctx.clinic_id, professional))


@router.put("/{professional_id}", response_model=ApiResponse[ProfessionalResponse])
async def update_professional(
    professional_id: UUID,
    data: ProfessionalUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("professionals.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ProfessionalResponse]:
    professional = await ProfessionalService.get(db, ctx.clinic_id, professional_id)
    if professional is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Professional not found")
    try:
        updated = await ProfessionalService.update(
            db, professional, data.model_dump(exclude_unset=True)
        )
    except UnknownSpecialtyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except UnknownUserLinkError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except UserLinkTakenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=await _to_response(db, ctx.clinic_id, updated))


_PHOTO_EXTENSION_BY_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
    "image/gif": "gif",
}
_PHOTO_MIME_BY_EXTENSION = {ext: mime for mime, ext in _PHOTO_EXTENSION_BY_MIME.items()}


def _photo_storage_path(clinic_id: UUID, professional_id: UUID, extension: str) -> str:
    return f"professionals/{clinic_id}/{professional_id}/photo.{extension}"


@router.post("/{professional_id}/photo", response_model=ApiResponse[ProfessionalResponse])
async def upload_professional_photo(
    professional_id: UUID,
    file: Annotated[UploadFile, File()],
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("professionals.write"))],
    __: Annotated[None, Depends(require_storage_room)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ProfessionalResponse]:
    professional = await ProfessionalService.get(db, ctx.clinic_id, professional_id)
    if professional is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Professional not found")

    validate_file_size(file)
    mime_type = validate_mime_type(file)
    extension = _PHOTO_EXTENSION_BY_MIME.get(mime_type)
    if extension is None:
        raise HTTPException(status_code=400, detail=f"Unsupported photo type '{mime_type}'")

    data = await file.read()
    storage = get_storage_backend()
    await storage.store(data, _photo_storage_path(ctx.clinic_id, professional_id, extension))

    photo_url = f"/api/v1/professionals/{professional_id}/photo"
    updated = await ProfessionalService.update(db, professional, {"photo_url": photo_url})
    return ApiResponse(data=await _to_response(db, ctx.clinic_id, updated))


@router.get("/{professional_id}/photo")
async def get_professional_photo(
    professional_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("professionals.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    professional = await ProfessionalService.get(db, ctx.clinic_id, professional_id)
    if professional is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Professional not found")

    storage = get_storage_backend()
    for extension, mime_type in _PHOTO_MIME_BY_EXTENSION.items():
        path = _photo_storage_path(ctx.clinic_id, professional_id, extension)
        if await storage.exists(path):
            return Response(content=await storage.retrieve(path), media_type=mime_type)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")
