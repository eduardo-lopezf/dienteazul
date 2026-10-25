"""Catalog module API router."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.errors import AppError
from app.core.schemas import ApiResponse, PaginatedApiResponse
from app.database import get_db

from .errors import catalog_error
from .packs import SpecialtyPackService, UnknownSpecialtyError
from .schemas import (
    CatalogItemBrief,
    CatalogItemCreate,
    CatalogItemResponse,
    CatalogItemSearchResult,
    CatalogItemUpdate,
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    OdontogramTreatmentResponse,
    PackSharedResponse,
    PackSubareaResponse,
    PackTreatmentResponse,
    SpecialtyBrief,
    SpecialtyCreate,
    SpecialtyItemsUpdate,
    SpecialtyPackDetailResponse,
    SpecialtyPackResponse,
    SpecialtyResponse,
    SpecialtySuggestion,
    SpecialtyUpdate,
    VatTypeCreate,
    VatTypeResponse,
    VatTypeUpdate,
)
from .seed import SUGGESTED_SPECIALTIES
from .service import (
    MAX_PAGE_SIZE,
    CatalogService,
    CategoryService,
    DuplicateSpecialtyError,
    OdontogramCatalogService,
    SessionTemplateError,
    SpecialtyService,
    UnknownCatalogItemError,
    VatTypeService,
)

router = APIRouter()


# ============================================================================
# Category Endpoints
# ============================================================================


@router.get("/categories", response_model=ApiResponse[list[CategoryResponse]])
async def list_categories(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = Query(default=False),
) -> ApiResponse[list[CategoryResponse]]:
    """List all treatment categories."""
    categories = await CategoryService.list_categories(
        db, ctx.clinic_id, include_inactive=include_inactive
    )
    return ApiResponse(data=[CategoryResponse.model_validate(c) for c in categories])


@router.get("/categories/{category_id}", response_model=ApiResponse[CategoryResponse])
async def get_category(
    category_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CategoryResponse]:
    """Get a treatment category by ID."""
    category = await CategoryService.get_category(db, ctx.clinic_id, category_id)
    if not category:
        raise catalog_error("catalog.category.not_found")
    return ApiResponse(data=CategoryResponse.model_validate(category))


@router.post(
    "/categories",
    response_model=ApiResponse[CategoryResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    data: CategoryCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CategoryResponse]:
    """Create a new treatment category."""
    # Check for duplicate key
    existing = await CategoryService.get_category_by_key(db, ctx.clinic_id, data.key)
    if existing:
        raise catalog_error(
            "catalog.category.duplicate", detail=f"Category with key '{data.key}' already exists"
        )

    category = await CategoryService.create_category(db, ctx.clinic_id, data.model_dump())
    return ApiResponse(data=CategoryResponse.model_validate(category))


@router.put("/categories/{category_id}", response_model=ApiResponse[CategoryResponse])
async def update_category(
    category_id: UUID,
    data: CategoryUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CategoryResponse]:
    """Update a treatment category."""
    category = await CategoryService.get_category(db, ctx.clinic_id, category_id)
    if not category:
        raise catalog_error("catalog.category.not_found")

    if category.is_system:
        raise catalog_error(
            "catalog.category.system_protected", detail="Cannot modify system category"
        )

    # Check key uniqueness if changing
    if data.key and data.key != category.key:
        existing = await CategoryService.get_category_by_key(db, ctx.clinic_id, data.key)
        if existing:
            raise catalog_error(
                "catalog.category.duplicate",
                detail=f"Category with key '{data.key}' already exists",
            )

    updated = await CategoryService.update_category(
        db, category, data.model_dump(exclude_unset=True)
    )
    return ApiResponse(data=CategoryResponse.model_validate(updated))


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Soft-delete a treatment category."""
    category = await CategoryService.get_category(db, ctx.clinic_id, category_id)
    if not category:
        raise catalog_error("catalog.category.not_found")

    if category.is_system:
        raise catalog_error(
            "catalog.category.system_protected", detail="Cannot delete system category"
        )

    await CategoryService.delete_category(db, category, soft=True)


# ============================================================================
# VAT Type Endpoints
# ============================================================================


@router.get("/vat-types", response_model=ApiResponse[list[VatTypeResponse]])
async def list_vat_types(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = Query(default=False),
) -> ApiResponse[list[VatTypeResponse]]:
    """List all VAT types for the clinic."""
    vat_types = await VatTypeService.list_vat_types(
        db, ctx.clinic_id, include_inactive=include_inactive
    )
    return ApiResponse(data=[VatTypeResponse.model_validate(v) for v in vat_types])


@router.get("/vat-types/default", response_model=ApiResponse[VatTypeResponse | None])
async def get_default_vat_type(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[VatTypeResponse | None]:
    """Get the default VAT type for the clinic."""
    vat_type = await VatTypeService.get_default_vat_type(db, ctx.clinic_id)
    return ApiResponse(data=VatTypeResponse.model_validate(vat_type) if vat_type else None)


@router.get("/vat-types/{vat_type_id}", response_model=ApiResponse[VatTypeResponse])
async def get_vat_type(
    vat_type_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[VatTypeResponse]:
    """Get a VAT type by ID."""
    vat_type = await VatTypeService.get_vat_type(db, ctx.clinic_id, vat_type_id)
    if not vat_type:
        raise catalog_error("catalog.vat_type.not_found")
    return ApiResponse(data=VatTypeResponse.model_validate(vat_type))


@router.post(
    "/vat-types",
    response_model=ApiResponse[VatTypeResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_vat_type(
    data: VatTypeCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[VatTypeResponse]:
    """Create a new VAT type."""
    vat_type = await VatTypeService.create_vat_type(db, ctx.clinic_id, data.model_dump())
    return ApiResponse(data=VatTypeResponse.model_validate(vat_type))


@router.put("/vat-types/{vat_type_id}", response_model=ApiResponse[VatTypeResponse])
async def update_vat_type(
    vat_type_id: UUID,
    data: VatTypeUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[VatTypeResponse]:
    """Update a VAT type."""
    vat_type = await VatTypeService.get_vat_type(db, ctx.clinic_id, vat_type_id)
    if not vat_type:
        raise catalog_error("catalog.vat_type.not_found")

    if vat_type.is_system:
        # System VAT types can only have is_default changed
        allowed_updates = {"is_default"}
        update_data = {
            k: v for k, v in data.model_dump(exclude_unset=True).items() if k in allowed_updates
        }
        if not update_data:
            raise catalog_error(
                "catalog.vat_type.system_protected",
                detail="Cannot modify system VAT type (only default status can be changed)",
            )
    else:
        update_data = data.model_dump(exclude_unset=True)

    updated = await VatTypeService.update_vat_type(db, ctx.clinic_id, vat_type, update_data)
    return ApiResponse(data=VatTypeResponse.model_validate(updated))


@router.delete("/vat-types/{vat_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vat_type(
    vat_type_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Soft-delete a VAT type."""
    vat_type = await VatTypeService.get_vat_type(db, ctx.clinic_id, vat_type_id)
    if not vat_type:
        raise catalog_error("catalog.vat_type.not_found")

    if vat_type.is_system:
        raise catalog_error(
            "catalog.vat_type.system_protected", detail="Cannot delete system VAT type"
        )

    if vat_type.is_default:
        raise catalog_error("catalog.vat_type.default_protected")

    await VatTypeService.delete_vat_type(db, vat_type)


# ============================================================================
# Specialty Endpoints
# ============================================================================


def _specialty_conflict(exc: DuplicateSpecialtyError) -> AppError:
    """409 naming the specialty that is in the way.

    A plain message, like every other conflict here: the app flattens an
    ``HTTPException`` to ``str(detail)``, so a structured body would reach the
    client as the printed form of a dict. The interesting distinction — the
    existing row is merely deactivated, so the answer is "switch it back on"
    rather than "you already have it" — is made in the form, which already
    holds the clinic's specialties, inactive ones included, and says so before
    anything is sent.
    """
    existing = exc.existing
    name = (
        existing.names.get("es")
        or existing.names.get("en")
        or next(iter(existing.names.values()), "")
    )
    state = "active" if existing.is_active else "inactive"
    return catalog_error(
        "catalog.specialty.duplicate", detail=f"Specialty already exists: {name} ({state})"
    )


@router.get("/specialties", response_model=ApiResponse[list[SpecialtyResponse]])
async def list_specialties(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = Query(default=False),
) -> ApiResponse[list[SpecialtyResponse]]:
    """List all specialties for the clinic."""
    specialties = await SpecialtyService.list_specialties(
        db, ctx.clinic_id, include_inactive=include_inactive
    )
    return ApiResponse(data=[SpecialtyResponse.model_validate(s) for s in specialties])


# --- Specialty packs ---------------------------------------------------------


def _pack_or_404(key: str) -> AppError:
    return catalog_error("catalog.specialty.not_found", detail=f"Unknown specialty: {key}")


@router.get("/specialty-packs", response_model=ApiResponse[list[SpecialtyPackResponse]])
async def list_specialty_packs(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[SpecialtyPackResponse]]:
    """Every recognised discipline, with its reference catalogue and
    whether this clinic has it enabled."""
    packs = await SpecialtyPackService.list(db, ctx.clinic_id)
    return ApiResponse(data=[SpecialtyPackResponse.model_validate(p) for p in packs])


@router.get("/specialty-packs/{key}", response_model=ApiResponse[SpecialtyPackDetailResponse])
async def get_specialty_pack(
    key: str,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SpecialtyPackDetailResponse]:
    """A discipline's reference treatments, grouped by sub-area, each with
    where the clinic stands on it: active, inactive, missing, customised."""
    try:
        detail = await SpecialtyPackService.detail(db, ctx.clinic_id, key)
    except UnknownSpecialtyError as error:
        raise _pack_or_404(key) from error
    return ApiResponse(
        data=SpecialtyPackDetailResponse(
            **SpecialtyPackResponse.model_validate(detail.status).model_dump(),
            subareas=[PackSubareaResponse.model_validate(group) for group in detail.subareas],
            shared=[
                PackSharedResponse(
                    specialty_key=group.key,
                    names=group.names,
                    treatments=[PackTreatmentResponse.model_validate(t) for t in group.treatments],
                )
                for group in detail.shared
            ],
        )
    )


@router.post("/specialty-packs/{key}/enable", response_model=ApiResponse[SpecialtyPackResponse])
async def enable_specialty_pack(
    key: str,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SpecialtyPackResponse]:
    """Add the discipline's reference treatments to the clinic's catalogue.
    Treatments the clinic already has are left as the clinic made them."""
    try:
        pack = await SpecialtyPackService.enable(db, ctx.clinic_id, key)
    except UnknownSpecialtyError as error:
        raise _pack_or_404(key) from error
    return ApiResponse(data=SpecialtyPackResponse.model_validate(pack))


@router.post("/specialty-packs/{key}/disable", response_model=ApiResponse[SpecialtyPackResponse])
async def disable_specialty_pack(
    key: str,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SpecialtyPackResponse]:
    """Take the discipline out of the clinic's catalogue. Nothing is
    deleted: its treatments are deactivated and come back on enabling."""
    try:
        pack = await SpecialtyPackService.disable(db, ctx.clinic_id, key)
    except UnknownSpecialtyError as error:
        raise _pack_or_404(key) from error
    return ApiResponse(data=SpecialtyPackResponse.model_validate(pack))


@router.post("/specialty-packs/{key}/restore", response_model=ApiResponse[SpecialtyPackResponse])
async def restore_specialty_pack(
    key: str,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SpecialtyPackResponse]:
    """Put the discipline's reference treatments back to the reference.

    **Overwrites** what the clinic changed on them — names, prices,
    durations. Treatments the clinic added itself are kept.
    """
    try:
        pack = await SpecialtyPackService.restore(db, ctx.clinic_id, key)
    except UnknownSpecialtyError as error:
        raise _pack_or_404(key) from error
    except ValueError as error:
        raise catalog_error(
            "catalog.specialty.restore_requires_enabled", detail=str(error)
        ) from error
    return ApiResponse(data=SpecialtyPackResponse.model_validate(pack))


@router.get(
    "/specialties/suggestions",
    response_model=ApiResponse[list[SpecialtySuggestion]],
)
async def list_specialty_suggestions(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[SpecialtySuggestion]]:
    """Recognised disciplines this clinic has not added yet.

    Declared before ``/specialties/{specialty_id}`` on purpose: the other
    route would match "suggestions" first and fail to read it as a UUID.
    """
    found = await SpecialtyService.suggestions(db, ctx.clinic_id)
    return ApiResponse(data=[SpecialtySuggestion(**item) for item in found])


@router.get("/specialties/{specialty_id}", response_model=ApiResponse[SpecialtyResponse])
async def get_specialty(
    specialty_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SpecialtyResponse]:
    """Get a specialty by ID."""
    specialty = await SpecialtyService.get_specialty(db, ctx.clinic_id, specialty_id)
    if not specialty:
        raise catalog_error("catalog.specialty.not_found")
    return ApiResponse(data=SpecialtyResponse.model_validate(specialty))


@router.post(
    "/specialties",
    response_model=ApiResponse[SpecialtyResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_specialty(
    data: SpecialtyCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SpecialtyResponse]:
    """Create a new specialty, unless the clinic already has it."""
    payload = data.model_dump()
    if payload.get("key") and payload["key"] not in {s["key"] for s in SUGGESTED_SPECIALTIES}:
        raise catalog_error("catalog.specialty.unknown_key")

    try:
        specialty = await SpecialtyService.create_specialty(db, ctx.clinic_id, payload)
    except DuplicateSpecialtyError as exc:
        raise _specialty_conflict(exc) from exc
    return ApiResponse(data=SpecialtyResponse.model_validate(specialty))


@router.put("/specialties/{specialty_id}", response_model=ApiResponse[SpecialtyResponse])
async def update_specialty(
    specialty_id: UUID,
    data: SpecialtyUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SpecialtyResponse]:
    """Update a specialty."""
    specialty = await SpecialtyService.get_specialty(db, ctx.clinic_id, specialty_id)
    if not specialty:
        raise catalog_error("catalog.specialty.not_found")

    try:
        updated = await SpecialtyService.update_specialty(
            db, specialty, data.model_dump(exclude_unset=True)
        )
    except DuplicateSpecialtyError as exc:
        raise _specialty_conflict(exc) from exc
    return ApiResponse(data=SpecialtyResponse.model_validate(updated))


@router.delete("/specialties/{specialty_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_specialty(
    specialty_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Soft-delete a specialty."""
    specialty = await SpecialtyService.get_specialty(db, ctx.clinic_id, specialty_id)
    if not specialty:
        raise catalog_error("catalog.specialty.not_found")

    await SpecialtyService.delete_specialty(db, specialty)


@router.get(
    "/specialties/{specialty_id}/items",
    response_model=ApiResponse[list[CatalogItemBrief]],
)
async def list_specialty_items(
    specialty_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[CatalogItemBrief]]:
    """List the treatments assigned to a specialty."""
    specialty = await SpecialtyService.get_specialty(db, ctx.clinic_id, specialty_id)
    if not specialty:
        raise catalog_error("catalog.specialty.not_found")

    items = await SpecialtyService.list_items(db, ctx.clinic_id, specialty_id)
    return ApiResponse(data=[CatalogItemBrief.model_validate(i) for i in items])


@router.put(
    "/specialties/{specialty_id}/items",
    response_model=ApiResponse[list[CatalogItemBrief]],
)
async def set_specialty_items(
    specialty_id: UUID,
    data: SpecialtyItemsUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[CatalogItemBrief]]:
    """Replace the treatments assigned to a specialty.

    The payload is authoritative: treatments absent from ``item_ids``
    lose the assignment.
    """
    specialty = await SpecialtyService.get_specialty(db, ctx.clinic_id, specialty_id)
    if not specialty:
        raise catalog_error("catalog.specialty.not_found")

    try:
        items = await SpecialtyService.set_items(db, ctx.clinic_id, specialty, data.item_ids)
    except UnknownCatalogItemError as exc:
        raise catalog_error("catalog.specialty.items_invalid", detail=str(exc)) from exc

    return ApiResponse(data=[CatalogItemBrief.model_validate(i) for i in items])


# ============================================================================
# Catalog Item Endpoints
# ============================================================================


@router.get("/items", response_model=PaginatedApiResponse[CatalogItemResponse])
async def list_items(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    category_id: UUID | None = Query(default=None),
    is_active: bool | None = Query(default=True),
    treatment_scope: str | None = Query(default=None),
    has_odontogram_mapping: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    include_deleted: bool = Query(default=False),
) -> PaginatedApiResponse[CatalogItemResponse]:
    """List catalog items with filtering and pagination.

    ``include_deleted`` surfaces removed treatments so an admin can restore
    one — set ``is_active: true`` on it and it comes back.
    """
    items, total = await CatalogService.list_items(
        db,
        ctx.clinic_id,
        page=page,
        page_size=page_size,
        category_id=category_id,
        is_active=is_active,
        treatment_scope=treatment_scope,
        has_odontogram_mapping=has_odontogram_mapping,
        search_query=search,
        include_deleted=include_deleted,
    )
    return PaginatedApiResponse(
        data=[CatalogItemResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/items/popular", response_model=ApiResponse[list[CatalogItemBrief]])
async def get_popular_items(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=8, ge=1, le=20),
) -> ApiResponse[list[CatalogItemBrief]]:
    """Get popular catalog items by usage frequency."""
    items = await CatalogService.get_popular_items(db, ctx.clinic_id, limit)
    return ApiResponse(data=[CatalogItemBrief.model_validate(i) for i in items])


@router.get("/items/recent", response_model=ApiResponse[list[CatalogItemBrief]])
async def get_recent_items(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=8, ge=1, le=20),
) -> ApiResponse[list[CatalogItemBrief]]:
    """Catalog items by how recently the clinic used them.

    The other axis from `/items/popular`: what the practice is doing now,
    not what it has done most. It is what the plan builder offers before
    anybody types.
    """
    items = await CatalogService.get_recent_items(db, ctx.clinic_id, limit)
    return ApiResponse(data=[CatalogItemBrief.model_validate(i) for i in items])


@router.get("/items/search", response_model=ApiResponse[list[CatalogItemSearchResult]])
async def search_items(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
) -> ApiResponse[list[CatalogItemSearchResult]]:
    """Search catalog items by name or code. Each hit says which discipline
    it is shown under, so a picker can group them."""
    items = await CatalogService.search_items(db, ctx.clinic_id, q, limit)
    primary = await CatalogService.primary_specialties(db, ctx.clinic_id, items)
    results = []
    for item in items:
        result = CatalogItemSearchResult.model_validate(item)
        specialty = primary.get(item.id)
        if specialty is not None:
            result.specialty = SpecialtyBrief.model_validate(specialty)
        results.append(result)
    return ApiResponse(data=results)


@router.get("/items/{item_id}", response_model=ApiResponse[CatalogItemResponse])
async def get_item(
    item_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CatalogItemResponse]:
    """Get a catalog item by ID."""
    item = await CatalogService.get_item(db, ctx.clinic_id, item_id)
    if not item:
        raise catalog_error("catalog.item.not_found")
    return ApiResponse(data=CatalogItemResponse.model_validate(item))


@router.post(
    "/items",
    response_model=ApiResponse[CatalogItemResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_item(
    data: CatalogItemCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CatalogItemResponse]:
    """Create a new catalog item."""
    # Verify category exists
    category = await CategoryService.get_category(db, ctx.clinic_id, data.category_id)
    if not category:
        raise catalog_error("catalog.item.category_not_found")

    # Check for duplicate code
    existing = await CatalogService.get_item_by_code(db, ctx.clinic_id, data.internal_code)
    if existing:
        raise catalog_error(
            "catalog.item.duplicate_code",
            detail=f"Item with code '{data.internal_code}' already exists",
        )

    try:
        item = await CatalogService.create_item(db, ctx.clinic_id, data.model_dump())
    except SessionTemplateError as exc:
        raise catalog_error("catalog.item.session_template_invalid", detail=str(exc)) from exc
    except ValueError as exc:
        # Unknown / other-clinic specialty id.
        raise catalog_error("catalog.item.specialties_invalid", detail=str(exc)) from exc

    # Reload to get relationships
    item = await CatalogService.get_item(db, ctx.clinic_id, item.id)
    return ApiResponse(data=CatalogItemResponse.model_validate(item))


@router.put("/items/{item_id}", response_model=ApiResponse[CatalogItemResponse])
async def update_item(
    item_id: UUID,
    data: CatalogItemUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CatalogItemResponse]:
    """Update a catalog item.

    Seeded (``is_system``) items are editable: a clinic must be able to set
    its own prices, durations and names, and deactivating one it does not
    offer is an update too. Only ``internal_code`` stays locked on them —
    it is the key the seeder matches on, so renaming it would make the next
    seed run recreate the original as a duplicate.

    Gated by ``catalog.write``, which only the admin role holds.

    Loads deleted items too, because reactivating one is how a removal is
    undone — see ``DELETE /items/{id}``.
    """
    item = await CatalogService.get_item(db, ctx.clinic_id, item_id, include_deleted=True)
    if not item:
        raise catalog_error("catalog.item.not_found")

    if item.is_system and data.internal_code and data.internal_code != item.internal_code:
        raise catalog_error("catalog.item.system_code_protected")

    # Verify category if changing
    if data.category_id and data.category_id != item.category_id:
        category = await CategoryService.get_category(db, ctx.clinic_id, data.category_id)
        if not category:
            raise catalog_error("catalog.item.category_not_found")

    # Check code uniqueness if changing
    if data.internal_code and data.internal_code != item.internal_code:
        existing = await CatalogService.get_item_by_code(db, ctx.clinic_id, data.internal_code)
        if existing:
            raise catalog_error(
                "catalog.item.duplicate_code",
                detail=f"Item with code '{data.internal_code}' already exists",
            )

    try:
        updated = await CatalogService.update_item(
            db, ctx.clinic_id, item, data.model_dump(exclude_unset=True)
        )
    except SessionTemplateError as exc:
        raise catalog_error("catalog.item.session_template_invalid", detail=str(exc)) from exc
    except ValueError as exc:
        # Unknown / other-clinic specialty id.
        raise catalog_error("catalog.item.specialties_invalid", detail=str(exc)) from exc

    # Reload to get fresh relationships
    updated = await CatalogService.get_item(db, ctx.clinic_id, item_id)
    return ApiResponse(data=CatalogItemResponse.model_validate(updated))


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Soft-delete a catalog item, seeded ones included.

    A clinic does not offer everything the starter catalog ships, and being
    unable to remove what it does not do left ~130 treatments cluttering every
    picker for good. Gated by ``catalog.write``, which only admin holds.

    The deletion is soft, and it is not a one-way door: the row survives
    (performed treatments, budget lines and plan templates point at it),
    ``GET /items?include_deleted=true`` finds it again, and updating it with
    ``is_active: true`` brings it back. Re-seeding does not resurrect it —
    the seeder matches on ``internal_code`` regardless of ``deleted_at`` and
    leaves it alone.
    """
    item = await CatalogService.get_item(db, ctx.clinic_id, item_id)
    if not item:
        raise catalog_error("catalog.item.not_found")

    await CatalogService.delete_item(db, item, hard=False)


# ============================================================================
# Odontogram Integration Endpoints
# ============================================================================


@router.get("/odontogram-treatments", response_model=ApiResponse[list[OdontogramTreatmentResponse]])
async def get_odontogram_treatments(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[OdontogramTreatmentResponse]]:
    """Get catalog items with odontogram mappings.

    Used by the TreatmentBar component to display available treatments.
    """
    treatments = await OdontogramCatalogService.get_odontogram_treatments(db, ctx.clinic_id)
    return ApiResponse(data=[OdontogramTreatmentResponse.model_validate(t) for t in treatments])


@router.get("/odontogram-treatments/by-category")
async def get_odontogram_treatments_by_category(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("catalog.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict[str, list[dict]]]:
    """Get catalog items with odontogram mappings grouped by clinical category.

    Convenience endpoint for TreatmentBar to avoid client-side grouping.
    """
    grouped = await OdontogramCatalogService.get_treatments_by_category(db, ctx.clinic_id)
    return ApiResponse(data=grouped)
