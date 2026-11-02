"""Purchasing services.

The rule this file exists to respect: **receiving does not write stock.**
It calls ``inventory.StockService.post``, which appends to the ledger and
moves the snapshot in the same transaction (ADR 0065). If purchasing ever
touched ``inv_stock_levels`` directly, the reconciliation that proves the
inventory honest would start reporting drift nobody could explain.

Importing `inventory` is allowed because it is in this module's
``depends`` and both live in the same App. The dependency runs one way:
`inventory` knows nothing about purchase orders.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.modules.inventory.models import InventoryItem, InventoryLot
from app.modules.inventory.service import ItemService, LocationService, StockService

from .models import OPEN_STATUSES, PurchaseOrder, PurchaseOrderLine, Supplier

ZERO = Decimal("0")
COST_STEP = Decimal("0.0001")


class PurchasingError(ValueError):
    """A refusal the caller can fix. Routers turn it into a 422."""


class SupplierService:
    """Who the clinic buys from."""

    @staticmethod
    async def list(
        db: AsyncSession, clinic_id: UUID, *, status: str | None = "active"
    ) -> list[Supplier]:
        filters = [Supplier.clinic_id == clinic_id]
        if status:
            filters.append(Supplier.status == status)
        rows = await db.execute(select(Supplier).where(*filters).order_by(Supplier.name))
        return list(rows.scalars().all())

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, supplier_id: UUID) -> Supplier | None:
        return await db.scalar(
            select(Supplier).where(Supplier.id == supplier_id, Supplier.clinic_id == clinic_id)
        )

    @staticmethod
    async def create(db: AsyncSession, clinic_id: UUID, data: dict) -> Supplier:
        name = str(data["name"]).strip()
        clash = await db.scalar(
            select(Supplier.id).where(Supplier.clinic_id == clinic_id, Supplier.name == name)
        )
        if clash is not None:
            raise PurchasingError(f"A supplier named '{name}' already exists")
        supplier = Supplier(clinic_id=clinic_id, **{**data, "name": name})
        db.add(supplier)
        await db.flush()
        return supplier

    @staticmethod
    async def update(db: AsyncSession, clinic_id: UUID, supplier_id: UUID, data: dict) -> Supplier:
        supplier = await SupplierService.get(db, clinic_id, supplier_id)
        if supplier is None:
            raise PurchasingError("Supplier not found")
        for field, value in data.items():
            setattr(supplier, field, value)
        await db.flush()
        return supplier

    @staticmethod
    async def archive(db: AsyncSession, clinic_id: UUID, supplier_id: UUID) -> None:
        """Archive, refusing while goods are still on the way.

        Hiding a supplier the clinic is waiting on would hide the orders
        with it, and those are what somebody chases when a delivery is
        late.
        """
        supplier = await SupplierService.get(db, clinic_id, supplier_id)
        if supplier is None:
            raise PurchasingError("Supplier not found")
        open_orders = await db.scalar(
            select(func.count())
            .select_from(PurchaseOrder)
            .where(
                PurchaseOrder.supplier_id == supplier_id,
                PurchaseOrder.clinic_id == clinic_id,
                PurchaseOrder.status.in_(OPEN_STATUSES),
            )
        )
        if open_orders:
            raise PurchasingError("This supplier still has open orders")
        supplier.status = "archived"
        await db.flush()


class OrderService:
    """What was ordered, and what is still coming."""

    @staticmethod
    async def _next_number(db: AsyncSession, clinic_id: UUID, when: date) -> str:
        """``P-2026-0007``, the clinic's own sequence.

        Taken under a transaction-scoped advisory lock keyed by clinic:
        two people pressing *create* in different processes would
        otherwise read the same maximum and be handed the same number,
        which the unique constraint then turns into a 500 for one of
        them (ADR 0051). The key is a hash, so two clinics may share a
        lock now and then — they wait microseconds for each other, which
        is cheaper than a second counter table.
        """
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"purchasing:{clinic_id}"},
        )
        prefix = f"P-{when.year}-"
        last = await db.scalar(
            select(func.max(PurchaseOrder.number)).where(
                PurchaseOrder.clinic_id == clinic_id,
                PurchaseOrder.number.like(f"{prefix}%"),
            )
        )
        nth = int(last.removeprefix(prefix)) + 1 if last else 1
        return f"{prefix}{nth:04d}"

    @staticmethod
    async def list(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        status: str | None = None,
        supplier_id: UUID | None = None,
        open_only: bool = False,
    ) -> list[PurchaseOrder]:
        filters = [PurchaseOrder.clinic_id == clinic_id]
        if status:
            filters.append(PurchaseOrder.status == status)
        if open_only:
            filters.append(PurchaseOrder.status.in_(OPEN_STATUSES))
        if supplier_id:
            filters.append(PurchaseOrder.supplier_id == supplier_id)
        rows = await db.execute(
            select(PurchaseOrder)
            .options(
                joinedload(PurchaseOrder.supplier),
                selectinload(PurchaseOrder.lines).joinedload(PurchaseOrderLine.item),
            )
            .where(*filters)
            .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.number.desc())
        )
        return list(rows.unique().scalars().all())

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, order_id: UUID) -> PurchaseOrder | None:
        return (
            (
                await db.execute(
                    select(PurchaseOrder)
                    .options(
                        joinedload(PurchaseOrder.supplier),
                        selectinload(PurchaseOrder.lines).joinedload(PurchaseOrderLine.item),
                    )
                    .where(PurchaseOrder.id == order_id, PurchaseOrder.clinic_id == clinic_id)
                )
            )
            .unique()
            .scalar_one_or_none()
        )

    @staticmethod
    async def create(
        db: AsyncSession, clinic_id: UUID, user_id: UUID | None, data: dict
    ) -> PurchaseOrder:
        supplier = await SupplierService.get(db, clinic_id, data["supplier_id"])
        if supplier is None:
            raise PurchasingError("Supplier not found")

        order = PurchaseOrder(
            clinic_id=clinic_id,
            supplier_id=supplier.id,
            number=await OrderService._next_number(db, clinic_id, data["order_date"]),
            status="draft",
            order_date=data["order_date"],
            expected_date=data.get("expected_date"),
            notes=data.get("notes"),
            created_by=user_id,
        )
        db.add(order)
        await db.flush()
        await OrderService._write_lines(db, clinic_id, order, data["lines"])
        await db.flush()
        return order

    @staticmethod
    async def update(
        db: AsyncSession, clinic_id: UUID, order_id: UUID, data: dict
    ) -> PurchaseOrder:
        """Change a draft. Once sent, the lines are what the supplier was
        told, and rewriting them would make the order disagree with the
        paper it was sent on."""
        order = await OrderService.get(db, clinic_id, order_id)
        if order is None:
            raise PurchasingError("Order not found")
        if order.status != "draft":
            raise PurchasingError("Only a draft order can be changed")

        lines = data.pop("lines", None)
        if data.get("supplier_id"):
            if await SupplierService.get(db, clinic_id, data["supplier_id"]) is None:
                raise PurchasingError("Supplier not found")
        for field, value in data.items():
            setattr(order, field, value)
        if lines is not None:
            order.lines.clear()
            await db.flush()
            await OrderService._write_lines(db, clinic_id, order, lines)
        await db.flush()
        return order

    @staticmethod
    async def send(db: AsyncSession, clinic_id: UUID, order_id: UUID) -> PurchaseOrder:
        order = await OrderService.get(db, clinic_id, order_id)
        if order is None:
            raise PurchasingError("Order not found")
        if order.status != "draft":
            raise PurchasingError("This order is already closed or sent")
        order.status = "sent"
        order.sent_at = datetime.now(UTC)
        await db.flush()
        return order

    @staticmethod
    async def cancel(db: AsyncSession, clinic_id: UUID, order_id: UUID) -> PurchaseOrder:
        """Cancel what has not arrived. What has is already in the ledger
        and stays there: the clinic received it."""
        order = await OrderService.get(db, clinic_id, order_id)
        if order is None:
            raise PurchasingError("Order not found")
        if order.status in ("received", "cancelled"):
            raise PurchasingError("This order is already closed")
        order.status = "cancelled"
        await db.flush()
        return order

    @staticmethod
    async def receive(
        db: AsyncSession, clinic_id: UUID, user_id: UUID | None, order_id: UUID, data: dict
    ) -> dict:
        """Book a delivery in: one inventory movement per line.

        Partial deliveries are the normal case, so each line carries what
        is still pending and the order's status follows from the lines
        rather than from what the person pressed.
        """
        order = await OrderService.get(db, clinic_id, order_id)
        if order is None:
            raise PurchasingError("Order not found")
        if order.status not in ("sent", "partially_received"):
            raise PurchasingError("This order cannot receive goods yet")

        by_id = {line.id: line for line in order.lines}
        location_id = await LocationService.default_id(db, clinic_id)
        movements: list[UUID] = []

        for entry in data["lines"]:
            line = by_id.get(entry["line_id"])
            if line is None:
                raise PurchasingError(f"Line {entry['line_id']} is not on this order")

            quantity = Decimal(entry["quantity"])
            pending = Decimal(line.quantity_ordered) - Decimal(line.quantity_received)
            if quantity > pending:
                raise PurchasingError(
                    f"{quantity} received but only {pending} is still pending on that line"
                )

            item = await ItemService.get(db, clinic_id, line.item_id)
            if item is None:  # pragma: no cover - the FK makes this unreachable
                raise PurchasingError("That article is not in the inventory")

            lot_id = None
            if item.tracks_lots:
                code = (entry.get("lot_code") or "").strip()
                if not code:
                    raise PurchasingError("This article tracks lots: name the lot")
                lot_id = await OrderService._lot_id(
                    db, clinic_id, item, code, entry.get("expires_on")
                )

            movement = await StockService.post(
                db,
                clinic_id,
                user_id,
                item_id=line.item_id,
                location_id=location_id,
                lot_id=lot_id,
                quantity_base=quantity,
                reason="purchase_receipt",
                note=data.get("note"),
                cost_per_base_unit=Decimal(line.unit_cost),
                # Opaque on purpose (ADR 0039): the inventory does not
                # know what a purchase order is, and this is what pairs
                # the movement with the line that caused it.
                source_ref={
                    "kind": "purchase_order",
                    "id": str(order.id),
                    "line": str(line.id),
                    "number": order.number,
                },
            )
            movements.append(movement.id)
            line.quantity_received = Decimal(line.quantity_received) + quantity
            await OrderService._reprice(db, clinic_id, item, quantity, Decimal(line.unit_cost))

        order.status = OrderService._status_after_receipt(order)
        if order.status == "received":
            order.completed_at = datetime.now(UTC)
        await db.flush()
        return {
            "order_status": order.status,
            "lines_received": len(data["lines"]),
            "movement_ids": movements,
        }

    # --- internals ----------------------------------------------------

    @staticmethod
    def _status_after_receipt(order: PurchaseOrder) -> str:
        outstanding = any(
            Decimal(line.quantity_received) < Decimal(line.quantity_ordered) for line in order.lines
        )
        return "partially_received" if outstanding else "received"

    @staticmethod
    async def _write_lines(
        db: AsyncSession, clinic_id: UUID, order: PurchaseOrder, lines: list[dict]
    ) -> None:
        for entry in lines:
            item = await ItemService.get(db, clinic_id, entry["item_id"])
            if item is None:
                raise PurchasingError("That article is not in the inventory")
            db.add(
                PurchaseOrderLine(
                    clinic_id=clinic_id,
                    order_id=order.id,
                    item_id=item.id,
                    quantity_ordered=Decimal(entry["quantity_ordered"]),
                    unit_cost=Decimal(entry["unit_cost"]),
                )
            )

    @staticmethod
    async def _lot_id(
        db: AsyncSession, clinic_id: UUID, item: InventoryItem, code: str, expires_on
    ) -> UUID:
        """The lot this delivery belongs to, created when it is new.

        A supplier sends the same batch twice as often as not, so an
        existing code is reused rather than refused.
        """
        existing = await db.scalar(
            select(InventoryLot).where(
                InventoryLot.clinic_id == clinic_id,
                InventoryLot.item_id == item.id,
                InventoryLot.lot_code == code,
            )
        )
        if existing is not None:
            # A date on the delivery note wins over no date on file; it
            # never overwrites one already recorded.
            if expires_on and existing.expires_on is None:
                existing.expires_on = expires_on
            return existing.id
        lot = InventoryLot(
            clinic_id=clinic_id, item_id=item.id, lot_code=code, expires_on=expires_on
        )
        db.add(lot)
        await db.flush()
        return lot.id

    @staticmethod
    async def _reprice(
        db: AsyncSession,
        clinic_id: UUID,
        item: InventoryItem,
        quantity: Decimal,
        unit_cost: Decimal,
    ) -> None:
        """Move the article's cost towards what this delivery cost.

        A weighted average over what is on hand: buying 100 gloves at a
        new price does not make the 300 already in the drawer cost that.
        The figure is a convenience on the article — the authoritative
        cost of any movement is the one stored on the movement itself.
        """
        totals = await StockService.item_totals(db, clinic_id, [item.id])
        # ``post`` ran before this, so the total already includes the
        # delivery; the previous stock is what it was before.
        on_hand_after = totals.get(item.id, ZERO)
        previous = on_hand_after - quantity
        old_cost = Decimal(item.cost_per_base_unit) if item.cost_per_base_unit else None

        if previous <= ZERO or old_cost is None:
            item.cost_per_base_unit = unit_cost.quantize(COST_STEP)
            return
        blended = (previous * old_cost + quantity * unit_cost) / on_hand_after
        item.cost_per_base_unit = blended.quantize(COST_STEP)
