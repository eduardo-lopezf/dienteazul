"""Purchasing module FastAPI router.

Endpoints under ``/api/v1/purchasing/``. Writes never commit here:
``commit_before_response`` does it for the whole request (ADR 0031).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .errors import purchasing_error, service_error
from .models import PurchaseOrder
from .schemas import (
    OrderCreate,
    OrderLineResponse,
    OrderResponse,
    OrderUpdate,
    ReceiptCreate,
    ReceiptResult,
    SupplierCreate,
    SupplierResponse,
    SupplierUpdate,
)
from .service import OrderService, PurchasingError, SupplierService

router = APIRouter(tags=["purchasing"])


#: Money is shown to the cent. A unit cost keeps four decimals — a pair
#: of gloves really does cost 0.1200 — but multiplying a 3-decimal
#: quantity by it gives seven, and a line total of `48.0000000` is not a
#: price anybody wrote on an order.
MONEY = Decimal("0.01")


def _order_payload(order: PurchaseOrder) -> OrderResponse:
    lines = [
        OrderLineResponse(
            id=line.id,
            item_id=line.item_id,
            item_name=line.item.name,
            item_code=line.item.code,
            base_unit=line.item.base_unit,
            tracks_lots=line.item.tracks_lots,
            quantity_ordered=line.quantity_ordered,
            quantity_received=line.quantity_received,
            quantity_pending=Decimal(line.quantity_ordered) - Decimal(line.quantity_received),
            unit_cost=line.unit_cost,
            line_total=(Decimal(line.quantity_ordered) * Decimal(line.unit_cost)).quantize(MONEY),
        )
        for line in order.lines
    ]
    return OrderResponse(
        id=order.id,
        number=order.number,
        status=order.status,
        supplier_id=order.supplier_id,
        supplier_name=order.supplier.name,
        order_date=order.order_date,
        expected_date=order.expected_date,
        notes=order.notes,
        sent_at=order.sent_at,
        completed_at=order.completed_at,
        total=sum((line.line_total for line in lines), Decimal("0")).quantize(MONEY),
        lines=lines,
    )


# --- suppliers -----------------------------------------------------------


@router.get("/suppliers", response_model=ApiResponse[list[SupplierResponse]])
async def list_suppliers(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("purchasing.suppliers.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = "active",
) -> ApiResponse[list[SupplierResponse]]:
    suppliers = await SupplierService.list(db, ctx.clinic_id, status=status_filter)
    return ApiResponse(data=[SupplierResponse.model_validate(s) for s in suppliers])


@router.post(
    "/suppliers",
    response_model=ApiResponse[SupplierResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_supplier(
    data: SupplierCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("purchasing.suppliers.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SupplierResponse]:
    try:
        supplier = await SupplierService.create(db, ctx.clinic_id, data.model_dump())
    except PurchasingError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=SupplierResponse.model_validate(supplier))


@router.put("/suppliers/{supplier_id}", response_model=ApiResponse[SupplierResponse])
async def update_supplier(
    supplier_id: UUID,
    data: SupplierUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("purchasing.suppliers.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SupplierResponse]:
    try:
        supplier = await SupplierService.update(
            db, ctx.clinic_id, supplier_id, data.model_dump(exclude_unset=True)
        )
    except PurchasingError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=SupplierResponse.model_validate(supplier))


@router.delete("/suppliers/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_supplier(
    supplier_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("purchasing.suppliers.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    try:
        await SupplierService.archive(db, ctx.clinic_id, supplier_id)
    except PurchasingError as exc:
        raise service_error(exc) from exc


# --- orders --------------------------------------------------------------


@router.get("/orders", response_model=ApiResponse[list[OrderResponse]])
async def list_orders(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("purchasing.orders.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    supplier_id: UUID | None = None,
    open_only: bool = False,
) -> ApiResponse[list[OrderResponse]]:
    """Not paginated: a clinic's open orders are a short list, and the
    screen filters rather than pages."""
    orders = await OrderService.list(
        db, ctx.clinic_id, status=status_filter, supplier_id=supplier_id, open_only=open_only
    )
    return ApiResponse(data=[_order_payload(order) for order in orders])


@router.post(
    "/orders", response_model=ApiResponse[OrderResponse], status_code=status.HTTP_201_CREATED
)
async def create_order(
    data: OrderCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("purchasing.orders.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[OrderResponse]:
    try:
        order = await OrderService.create(db, ctx.clinic_id, ctx.user_id, data.model_dump())
    except PurchasingError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=_order_payload(await OrderService.get(db, ctx.clinic_id, order.id)))


@router.get("/orders/{order_id}", response_model=ApiResponse[OrderResponse])
async def get_order(
    order_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("purchasing.orders.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[OrderResponse]:
    order = await OrderService.get(db, ctx.clinic_id, order_id)
    if order is None:
        raise purchasing_error("purchasing.order.not_found")
    return ApiResponse(data=_order_payload(order))


@router.put("/orders/{order_id}", response_model=ApiResponse[OrderResponse])
async def update_order(
    order_id: UUID,
    data: OrderUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("purchasing.orders.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[OrderResponse]:
    try:
        await OrderService.update(db, ctx.clinic_id, order_id, data.model_dump(exclude_unset=True))
    except PurchasingError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=_order_payload(await OrderService.get(db, ctx.clinic_id, order_id)))


@router.post("/orders/{order_id}/send", response_model=ApiResponse[OrderResponse])
async def send_order(
    order_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("purchasing.orders.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[OrderResponse]:
    """Mark the order as placed. Nothing is sent anywhere: the clinic
    orders by phone, email or the supplier's own portal, and this records
    that it did."""
    try:
        await OrderService.send(db, ctx.clinic_id, order_id)
    except PurchasingError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=_order_payload(await OrderService.get(db, ctx.clinic_id, order_id)))


@router.post("/orders/{order_id}/cancel", response_model=ApiResponse[OrderResponse])
async def cancel_order(
    order_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("purchasing.orders.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[OrderResponse]:
    try:
        await OrderService.cancel(db, ctx.clinic_id, order_id)
    except PurchasingError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=_order_payload(await OrderService.get(db, ctx.clinic_id, order_id)))


@router.post(
    "/orders/{order_id}/receive",
    response_model=ApiResponse[ReceiptResult],
    status_code=status.HTTP_201_CREATED,
)
async def receive_order(
    order_id: UUID,
    data: ReceiptCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("purchasing.orders.receive"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ReceiptResult]:
    """Book a delivery in. Each line becomes a movement in the stock
    ledger, which is the only place stock changes (ADR 0065)."""
    try:
        result = await OrderService.receive(
            db, ctx.clinic_id, ctx.user_id, order_id, data.model_dump()
        )
    except PurchasingError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=ReceiptResult(**result))
