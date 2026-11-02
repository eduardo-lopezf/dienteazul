"""Inventory module FastAPI router.

Endpoints under ``/api/v1/inventory/``. Writes never commit here:
``commit_before_response`` does it for the whole request (ADR 0031).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse, PaginatedApiResponse
from app.database import get_db

from .errors import inventory_error, service_error
from .integrations import catalogue, patients
from .schemas import (
    CatalogTreatmentOption,
    CountCreate,
    CountResult,
    ImplantRecord,
    ImplantTraceResponse,
    ItemCreate,
    ItemResponse,
    ItemUpdate,
    LocationCreate,
    LocationResponse,
    LocationUpdate,
    LotCreate,
    LotResponse,
    MaterialResponse,
    MaterialsSet,
    MovementCreate,
    MovementResponse,
    ReconcileResult,
    StockAlerts,
    StockLine,
    TransferCreate,
    TreatmentMaterialsResponse,
    UserBrief,
)
from .service import (
    EXPIRY_WINDOW_DAYS,
    ImplantService,
    InventoryError,
    ItemService,
    LocationService,
    LotService,
    MaterialService,
    StockService,
)

# No prefix: ``_mount_one`` mounts every module router at
# ``/api/v1/<module name>``, so one here would give
# ``/api/v1/inventory/inventory/...``.
router = APIRouter(tags=["inventory"])


def _movement_payload(movement) -> MovementResponse:
    return MovementResponse(
        id=movement.id,
        item_id=movement.item_id,
        item_name=movement.item.name,
        location_id=movement.location_id,
        location_name=movement.location.name,
        lot_id=movement.lot_id,
        lot_code=movement.lot.lot_code if movement.lot else None,
        quantity_base=movement.quantity_base,
        reason=movement.reason,
        note=movement.note,
        source_ref=movement.source_ref,
        performed_by=movement.performed_by,
        performed_by_user=(
            UserBrief.model_validate(movement.performer) if movement.performer else None
        ),
        cost_per_base_unit=movement.cost_per_base_unit,
        created_at=movement.created_at,
    )


# --- stock ---------------------------------------------------------------
# Declared before ``/items/{item_id}`` and friends: FastAPI resolves in
# registration order, and "alerts" would otherwise parse as an id.


@router.get("/stock", response_model=ApiResponse[list[StockLine]])
async def list_stock(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.stock.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    item_id: UUID | None = None,
    location_id: UUID | None = None,
    category: str | None = None,
    search: str | None = None,
    include_empty: bool = False,
) -> ApiResponse[list[StockLine]]:
    """What is on hand, one row per article/location/lot.

    Not paginated, and that is a decision: a clinic's article list is
    hundreds of rows, the screen filters rather than pages, and a reorder
    decision needs the whole picture at once.
    """
    lines = await StockService.levels(
        db,
        ctx.clinic_id,
        item_id=item_id,
        location_id=location_id,
        category=category,
        search=search,
        include_empty=include_empty,
    )
    return ApiResponse(data=[StockLine(**line) for line in lines])


@router.get("/stock/alerts", response_model=ApiResponse[StockAlerts])
async def stock_alerts(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.stock.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    window_days: Annotated[int, Query(ge=1, le=365)] = EXPIRY_WINDOW_DAYS,
) -> ApiResponse[StockAlerts]:
    alerts = await StockService.alerts(db, ctx.clinic_id, window_days=window_days)
    return ApiResponse(
        data=StockAlerts(
            low_stock=[StockLine(**line) for line in alerts["low_stock"]],
            expiring=[StockLine(**line) for line in alerts["expiring"]],
            expired=[StockLine(**line) for line in alerts["expired"]],
        )
    )


@router.post(
    "/stock/count",
    response_model=ApiResponse[CountResult],
    status_code=status.HTTP_201_CREATED,
)
async def close_count(
    data: CountCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.stock.adjust"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CountResult]:
    """Post the differences of a physical count as adjustments."""
    try:
        result = await StockService.count(db, ctx.clinic_id, ctx.user_id, data.model_dump())
    except InventoryError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=CountResult(**result))


@router.post("/stock/reconcile", response_model=ApiResponse[ReconcileResult])
async def reconcile_stock(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.stock.adjust"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ReconcileResult]:
    """Rebuild the snapshot from the ledger (ADR 0065).

    Safe to run at any time, and expected to correct nothing.
    """
    return ApiResponse(data=ReconcileResult(**await StockService.reconcile(db, ctx.clinic_id)))


# --- movements -----------------------------------------------------------


@router.get("/movements", response_model=PaginatedApiResponse[MovementResponse])
async def list_movements(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.stock.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    item_id: UUID | None = None,
    location_id: UUID | None = None,
    reason: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> PaginatedApiResponse[MovementResponse]:
    movements, total = await StockService.movements(
        db,
        ctx.clinic_id,
        page=page,
        page_size=page_size,
        item_id=item_id,
        location_id=location_id,
        reason=reason,
        date_from=date_from,
        date_to=date_to,
    )
    return PaginatedApiResponse(
        data=[_movement_payload(m) for m in movements],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/movements",
    response_model=ApiResponse[MovementResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_movement(
    data: MovementCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.stock.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[MovementResponse]:
    """Record one movement. An adjustment needs ``inventory.stock.adjust``."""
    if data.reason == "adjustment":
        raise inventory_error(
            "inventory.request.invalid",
            detail="Post an adjustment through /stock/count, which records what was counted",
        )
    try:
        movement = await StockService.post(
            db,
            ctx.clinic_id,
            ctx.user_id,
            item_id=data.item_id,
            location_id=data.location_id,
            lot_id=data.lot_id,
            quantity_base=data.quantity_base,
            reason=data.reason,
            note=data.note,
            cost_per_base_unit=data.cost_per_base_unit,
            source_ref=data.source_ref,
        )
    except InventoryError as exc:
        raise service_error(exc) from exc
    reloaded = await StockService.get_movement(db, ctx.clinic_id, movement.id)
    return ApiResponse(data=_movement_payload(reloaded))


@router.post(
    "/movements/transfer",
    response_model=ApiResponse[list[MovementResponse]],
    status_code=status.HTTP_201_CREATED,
)
async def transfer_stock(
    data: TransferCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.stock.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[MovementResponse]]:
    """Move stock between two locations: two paired ledger lines."""
    try:
        moved = await StockService.transfer(db, ctx.clinic_id, ctx.user_id, data.model_dump())
    except InventoryError as exc:
        raise service_error(exc) from exc
    reloaded = [await StockService.get_movement(db, ctx.clinic_id, m.id) for m in moved]
    return ApiResponse(data=[_movement_payload(m) for m in reloaded])


# --- implant traceability (layer 4) --------------------------------------


async def _trace_payloads(db, clinic_id, traces) -> list[ImplantTraceResponse]:
    """Traces with the patient's name attached, when there is one to attach.

    The name comes from the ``PatientDirectory`` contract. With the
    Patients App off the ids stay and the names are null — the trace is
    this module's data and does not stop existing because a neighbour is
    switched off (ADR 0037).
    """
    directory = patients()
    briefs = (
        await directory.briefs(db, clinic_id, [trace.patient_id for trace in traces])
        if directory and traces
        else {}
    )
    return [
        ImplantTraceResponse(
            id=trace.id,
            patient_id=trace.patient_id,
            first_name=briefs[trace.patient_id].first_name if trace.patient_id in briefs else None,
            last_name=briefs[trace.patient_id].last_name if trace.patient_id in briefs else None,
            item_id=trace.item_id,
            item_code=trace.item.code,
            item_name=trace.item.name,
            lot_id=trace.lot_id,
            lot_code=trace.lot.lot_code,
            expires_on=trace.lot.expires_on,
            placed_on=trace.placed_on,
            tooth_number=trace.tooth_number,
            serial_number=trace.serial_number,
            notes=trace.notes,
        )
        for trace in traces
    ]


@router.get("/implants", response_model=ApiResponse[list[ImplantTraceResponse]])
async def list_implants(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.implants.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    patient_id: UUID | None = None,
    lot_id: UUID | None = None,
    item_id: UUID | None = None,
) -> ApiResponse[list[ImplantTraceResponse]]:
    """Which devices went into which patients.

    ``lot_id`` is the question this whole table exists to answer: a
    manufacturer withdraws a batch and the clinic needs the list of
    people carrying it, today, by name.
    """
    traces = await ImplantService.list(
        db, ctx.clinic_id, patient_id=patient_id, lot_id=lot_id, item_id=item_id
    )
    return ApiResponse(data=await _trace_payloads(db, ctx.clinic_id, traces))


@router.post(
    "/implants",
    response_model=ApiResponse[ImplantTraceResponse],
    status_code=status.HTTP_201_CREATED,
)
async def record_implant(
    data: ImplantRecord,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.implants.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ImplantTraceResponse]:
    """Record a device placed in a patient, and take it off the shelf.

    One act: the movement and the trace are written in the same
    transaction, so a trace can never exist without the stock having
    moved, nor the stock move with nobody carrying the device.
    """
    try:
        trace = await ImplantService.record(db, ctx.clinic_id, ctx.user_id, data.model_dump())
    except InventoryError as exc:
        raise service_error(exc) from exc
    payloads = await _trace_payloads(
        db, ctx.clinic_id, await ImplantService.list(db, ctx.clinic_id, patient_id=data.patient_id)
    )
    return ApiResponse(data=next(p for p in payloads if p.id == trace.id))


# --- materials per treatment ---------------------------------------------


def _localized(names: dict[str, str]) -> str:
    """The catalogue's localized name, collapsed the way its own tools do."""
    return names.get("es") or names.get("en") or next(iter(names.values()), "")


@router.get("/materials", response_model=ApiResponse[list[TreatmentMaterialsResponse]])
async def list_materials(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.items.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[TreatmentMaterialsResponse]]:
    """Every treatment that has a materials list, with its lines.

    The treatment's own name comes from the ``TreatmentCatalogue``
    contract. With the Treatments App off there is no supplier, the
    names are null and the lists are still here (ADR 0037).
    """
    rows = await MaterialService.list(db, ctx.clinic_id)
    by_treatment: dict[UUID, list] = {}
    for row in rows:
        by_treatment.setdefault(row.catalog_item_id, []).append(row)

    catalogue_provider = catalogue()
    briefs = (
        await catalogue_provider.briefs(db, ctx.clinic_id, list(by_treatment))
        if catalogue_provider and by_treatment
        else {}
    )

    return ApiResponse(
        data=[
            TreatmentMaterialsResponse(
                catalog_item_id=catalog_item_id,
                treatment_code=briefs[catalog_item_id].internal_code
                if catalog_item_id in briefs
                else None,
                treatment_name=_localized(briefs[catalog_item_id].names)
                if catalog_item_id in briefs
                else None,
                lines=[
                    MaterialResponse(
                        item_id=line.item_id,
                        item_code=line.item.code,
                        item_name=line.item.name,
                        base_unit=line.item.base_unit,
                        tracks_lots=line.item.tracks_lots,
                        quantity_base=line.quantity_base,
                    )
                    for line in lines
                ],
            )
            for catalog_item_id, lines in by_treatment.items()
        ]
    )


@router.get("/materials/treatments", response_model=ApiResponse[list[CatalogTreatmentOption]])
async def list_catalogue_treatments(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.items.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[CatalogTreatmentOption]]:
    """The treatments a materials list can be written for.

    Empty when the Treatments App is off, which is the honest answer:
    there is nothing to pick from.
    """
    catalogue_provider = catalogue()
    if catalogue_provider is None:
        return ApiResponse(data=[])
    return ApiResponse(
        data=[
            CatalogTreatmentOption(
                id=brief.id, internal_code=brief.internal_code, name=_localized(brief.names)
            )
            for brief in await catalogue_provider.list_active(db, ctx.clinic_id)
        ]
    )


@router.put("/materials/{catalog_item_id}", response_model=ApiResponse[list[MaterialResponse]])
async def set_materials(
    catalog_item_id: UUID,
    data: MaterialsSet,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.items.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[MaterialResponse]]:
    """Replace a treatment's materials list. An empty list clears it."""
    try:
        rows = await MaterialService.set_for_treatment(
            db, ctx.clinic_id, catalog_item_id, [line.model_dump() for line in data.lines]
        )
    except InventoryError as exc:
        raise service_error(exc) from exc
    return ApiResponse(
        data=[
            MaterialResponse(
                item_id=row.item_id,
                item_code=row.item.code,
                item_name=row.item.name,
                base_unit=row.item.base_unit,
                tracks_lots=row.item.tracks_lots,
                quantity_base=row.quantity_base,
            )
            for row in rows
        ]
    )


# --- articles ------------------------------------------------------------


@router.get("/items", response_model=PaginatedApiResponse[ItemResponse])
async def list_items(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.items.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    category: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = "active",
) -> PaginatedApiResponse[ItemResponse]:
    items, total = await ItemService.list(
        db,
        ctx.clinic_id,
        page=page,
        page_size=page_size,
        search=search,
        category=category,
        status=status_filter,
    )
    return PaginatedApiResponse(
        data=[ItemResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/items", response_model=ApiResponse[ItemResponse], status_code=status.HTTP_201_CREATED
)
async def create_item(
    data: ItemCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.items.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ItemResponse]:
    try:
        item = await ItemService.create(db, ctx.clinic_id, data.model_dump())
    except InventoryError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=ItemResponse.model_validate(item))


@router.get("/items/{item_id}", response_model=ApiResponse[ItemResponse])
async def get_item(
    item_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.items.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ItemResponse]:
    item = await ItemService.get(db, ctx.clinic_id, item_id)
    if item is None:
        raise inventory_error("inventory.item.not_found")
    return ApiResponse(data=ItemResponse.model_validate(item))


@router.put("/items/{item_id}", response_model=ApiResponse[ItemResponse])
async def update_item(
    item_id: UUID,
    data: ItemUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.items.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ItemResponse]:
    try:
        item = await ItemService.update(
            db, ctx.clinic_id, item_id, data.model_dump(exclude_unset=True)
        )
    except InventoryError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=ItemResponse.model_validate(item))


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_item(
    item_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.items.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Archive the article. The ledger keeps every movement of it."""
    try:
        await ItemService.archive(db, ctx.clinic_id, item_id)
    except InventoryError as exc:
        raise service_error(exc) from exc


@router.get("/items/{item_id}/lots", response_model=ApiResponse[list[LotResponse]])
async def list_lots(
    item_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.stock.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[LotResponse]]:
    lots = await LotService.list_for_item(db, ctx.clinic_id, item_id)
    return ApiResponse(data=[LotResponse.model_validate(lot) for lot in lots])


@router.post(
    "/items/{item_id}/lots",
    response_model=ApiResponse[LotResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_lot(
    item_id: UUID,
    data: LotCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.stock.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LotResponse]:
    try:
        lot = await LotService.create(db, ctx.clinic_id, item_id, data.model_dump())
    except InventoryError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=LotResponse.model_validate(lot))


# --- locations -----------------------------------------------------------


@router.get("/locations", response_model=ApiResponse[list[LocationResponse]])
async def list_locations(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.stock.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = "active",
) -> ApiResponse[list[LocationResponse]]:
    locations = await LocationService.list(db, ctx.clinic_id, status=status_filter)
    return ApiResponse(data=[LocationResponse.model_validate(loc) for loc in locations])


@router.post(
    "/locations",
    response_model=ApiResponse[LocationResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_location(
    data: LocationCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.items.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LocationResponse]:
    try:
        location = await LocationService.create(db, ctx.clinic_id, data.model_dump())
    except InventoryError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=LocationResponse.model_validate(location))


@router.put("/locations/{location_id}", response_model=ApiResponse[LocationResponse])
async def update_location(
    location_id: UUID,
    data: LocationUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.items.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LocationResponse]:
    try:
        location = await LocationService.update(
            db, ctx.clinic_id, location_id, data.model_dump(exclude_unset=True)
        )
    except InventoryError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=LocationResponse.model_validate(location))


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_location(
    location_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("inventory.items.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    try:
        await LocationService.archive(db, ctx.clinic_id, location_id)
    except InventoryError as exc:
        raise service_error(exc) from exc
