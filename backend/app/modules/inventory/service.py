"""Inventory services.

One rule governs this file, and it is ADR 0065: **the ledger is the
truth and the snapshot is derived from it.** Every change to stock goes
through :meth:`StockService.post`, which appends one ``inv_movements``
row and updates the matching ``inv_stock_levels`` row inside the same
transaction. Nothing else in the codebase may write either table, which
is what makes :meth:`StockService.reconcile` able to assert they agree.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.events import EventType, event_bus
from app.core.ids import uuid7

from .models import (
    ADJUSTMENT_REASON,
    ImplantTrace,
    InventoryItem,
    InventoryLocation,
    InventoryLot,
    InventoryMovement,
    InventoryStockLevel,
    TreatmentMaterial,
)

#: Reasons whose sign is implied by the reason itself.
_INCOMING = {"purchase_receipt"}
_OUTGOING = {"consumption", "expiry_write_off", "return"}

#: Reasons that carry the sign they were given. An adjustment can go
#: either way by nature, and a transfer is built by
#: :meth:`StockService.transfer` as a negative leg and a positive one —
#: the only caller that already knows which way each goes.
_SIGNED_BY_CALLER = {ADJUSTMENT_REASON, "transfer"}

#: The ledger's scale (``NUMERIC(12, 3)``). Quantities are normalised to
#: it on the way in, so a figure read back equals the figure stored
#: rather than whatever scale the request happened to carry.
QUANTITY_STEP = Decimal("0.001")

#: How far ahead an expiry is worth warning about. Clinic-wide for now;
#: a per-article override is an open question in the brief.
EXPIRY_WINDOW_DAYS = 60

ZERO = Decimal("0")


class InventoryError(ValueError):
    """A refusal the caller can fix. Routers turn it into a 422."""


def _level_match(item_id: UUID, location_id: UUID, lot_id: UUID | None) -> list:
    """Filters that address exactly one level row.

    ``lot_id IS NULL`` has to be written out: ``== None`` compiles to
    ``= NULL``, which matches nothing, and the level would be inserted
    again on every movement of a lot-less article.
    """
    return [
        InventoryStockLevel.item_id == item_id,
        InventoryStockLevel.location_id == location_id,
        InventoryStockLevel.lot_id.is_(None)
        if lot_id is None
        else InventoryStockLevel.lot_id == lot_id,
    ]


class ItemService:
    """Article master data."""

    @staticmethod
    async def list(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        category: str | None = None,
        status: str | None = "active",
    ) -> tuple[list[InventoryItem], int]:
        filters = [InventoryItem.clinic_id == clinic_id]
        if status:
            filters.append(InventoryItem.status == status)
        if category:
            filters.append(InventoryItem.category == category)
        if search:
            pattern = f"%{search.strip()}%"
            filters.append(InventoryItem.name.ilike(pattern) | InventoryItem.code.ilike(pattern))

        total = await db.scalar(select(func.count()).select_from(InventoryItem).where(*filters))
        rows = await db.execute(
            select(InventoryItem)
            .where(*filters)
            .order_by(InventoryItem.name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.scalars().all()), int(total or 0)

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, item_id: UUID) -> InventoryItem | None:
        return await db.scalar(
            select(InventoryItem).where(
                InventoryItem.id == item_id, InventoryItem.clinic_id == clinic_id
            )
        )

    @staticmethod
    async def create(db: AsyncSession, clinic_id: UUID, data: dict) -> InventoryItem:
        code = str(data["code"]).strip()
        existing = await db.scalar(
            select(InventoryItem.id).where(
                InventoryItem.clinic_id == clinic_id, InventoryItem.code == code
            )
        )
        if existing is not None:
            raise InventoryError(f"An article with code '{code}' already exists")

        presentations = [
            {"label": p["label"], "factor": str(p["factor"])}
            for p in data.pop("purchase_presentations", []) or []
        ]
        item = InventoryItem(
            clinic_id=clinic_id, **{**data, "code": code, "purchase_presentations": presentations}
        )
        db.add(item)
        await db.flush()
        return item

    @staticmethod
    async def update(db: AsyncSession, clinic_id: UUID, item_id: UUID, data: dict) -> InventoryItem:
        item = await ItemService.get(db, clinic_id, item_id)
        if item is None:
            raise InventoryError("Article not found")
        if "purchase_presentations" in data and data["purchase_presentations"] is not None:
            data["purchase_presentations"] = [
                {"label": p["label"], "factor": str(p["factor"])}
                for p in data["purchase_presentations"]
            ]
        for field, value in data.items():
            setattr(item, field, value)
        await db.flush()
        return item

    @staticmethod
    async def archive(db: AsyncSession, clinic_id: UUID, item_id: UUID) -> None:
        """Archive, never delete: the ledger references the article forever."""
        item = await ItemService.get(db, clinic_id, item_id)
        if item is None:
            raise InventoryError("Article not found")
        item.status = "archived"
        await db.flush()


class LocationService:
    """Where stock sits."""

    @staticmethod
    async def list(
        db: AsyncSession, clinic_id: UUID, *, status: str | None = "active"
    ) -> list[InventoryLocation]:
        filters = [InventoryLocation.clinic_id == clinic_id]
        if status:
            filters.append(InventoryLocation.status == status)
        rows = await db.execute(
            select(InventoryLocation)
            .where(*filters)
            .order_by(InventoryLocation.is_default.desc(), InventoryLocation.name)
        )
        return list(rows.scalars().all())

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, location_id: UUID) -> InventoryLocation | None:
        return await db.scalar(
            select(InventoryLocation).where(
                InventoryLocation.id == location_id,
                InventoryLocation.clinic_id == clinic_id,
            )
        )

    @staticmethod
    async def default_id(db: AsyncSession, clinic_id: UUID) -> UUID:
        """The location a movement lands in when the caller names none.

        A clinic with no locations gets one: the alternative is refusing
        the first receipt somebody tries to record, which reads as the
        feature being broken rather than as a setup step.
        """
        existing = await db.scalar(
            select(InventoryLocation.id).where(
                InventoryLocation.clinic_id == clinic_id,
                InventoryLocation.status == "active",
                InventoryLocation.is_default.is_(True),
            )
        )
        if existing is not None:
            return existing
        any_location = await db.scalar(
            select(InventoryLocation.id)
            .where(
                InventoryLocation.clinic_id == clinic_id,
                InventoryLocation.status == "active",
            )
            .order_by(InventoryLocation.created_at)
            .limit(1)
        )
        if any_location is not None:
            return any_location
        created = await LocationService.create(
            db, clinic_id, {"name": "Almacén", "kind": "warehouse", "is_default": True}
        )
        return created.id

    @staticmethod
    async def create(db: AsyncSession, clinic_id: UUID, data: dict) -> InventoryLocation:
        name = str(data["name"]).strip()
        clash = await db.scalar(
            select(InventoryLocation.id).where(
                InventoryLocation.clinic_id == clinic_id, InventoryLocation.name == name
            )
        )
        if clash is not None:
            raise InventoryError(f"A location named '{name}' already exists")
        location = InventoryLocation(clinic_id=clinic_id, **{**data, "name": name})
        db.add(location)
        if location.is_default:
            await LocationService._clear_other_defaults(db, clinic_id, location)
        await db.flush()
        return location

    @staticmethod
    async def update(
        db: AsyncSession, clinic_id: UUID, location_id: UUID, data: dict
    ) -> InventoryLocation:
        location = await LocationService.get(db, clinic_id, location_id)
        if location is None:
            raise InventoryError("Location not found")
        for field, value in data.items():
            setattr(location, field, value)
        if location.is_default:
            await LocationService._clear_other_defaults(db, clinic_id, location)
        await db.flush()
        return location

    @staticmethod
    async def archive(db: AsyncSession, clinic_id: UUID, location_id: UUID) -> None:
        """Archive a location, refusing while it still holds stock.

        Hiding a place that has material in it would take that material
        out of every total while it is still on a shelf.
        """
        location = await LocationService.get(db, clinic_id, location_id)
        if location is None:
            raise InventoryError("Location not found")
        on_hand = await db.scalar(
            select(func.coalesce(func.sum(InventoryStockLevel.quantity), 0)).where(
                InventoryStockLevel.location_id == location_id,
                InventoryStockLevel.clinic_id == clinic_id,
            )
        )
        if Decimal(on_hand or 0) != ZERO:
            raise InventoryError("This location still holds stock; move it out first")
        location.status = "archived"
        location.is_default = False
        await db.flush()

    @staticmethod
    async def _clear_other_defaults(
        db: AsyncSession, clinic_id: UUID, keep: InventoryLocation
    ) -> None:
        rows = await db.execute(
            select(InventoryLocation).where(
                InventoryLocation.clinic_id == clinic_id,
                InventoryLocation.is_default.is_(True),
            )
        )
        for other in rows.scalars().all():
            if other.id != keep.id:
                other.is_default = False


class LotService:
    """Supplier batches and their expiry dates."""

    @staticmethod
    async def list_for_item(db: AsyncSession, clinic_id: UUID, item_id: UUID) -> list[InventoryLot]:
        rows = await db.execute(
            select(InventoryLot)
            .where(InventoryLot.clinic_id == clinic_id, InventoryLot.item_id == item_id)
            # Nulls last: a lot with no date is not the next one to use.
            .order_by(InventoryLot.expires_on.asc().nullslast(), InventoryLot.lot_code)
        )
        return list(rows.scalars().all())

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, lot_id: UUID) -> InventoryLot | None:
        return await db.scalar(
            select(InventoryLot).where(
                InventoryLot.id == lot_id, InventoryLot.clinic_id == clinic_id
            )
        )

    @staticmethod
    async def create(db: AsyncSession, clinic_id: UUID, item_id: UUID, data: dict) -> InventoryLot:
        item = await ItemService.get(db, clinic_id, item_id)
        if item is None:
            raise InventoryError("Article not found")
        if not item.tracks_lots:
            raise InventoryError("This article does not track lots")
        code = str(data["lot_code"]).strip()
        clash = await db.scalar(
            select(InventoryLot.id).where(
                InventoryLot.clinic_id == clinic_id,
                InventoryLot.item_id == item_id,
                InventoryLot.lot_code == code,
            )
        )
        if clash is not None:
            raise InventoryError(f"Lot '{code}' already exists for this article")
        lot = InventoryLot(
            clinic_id=clinic_id, item_id=item_id, lot_code=code, expires_on=data.get("expires_on")
        )
        db.add(lot)
        await db.flush()
        return lot


class ImplantService:
    """Which batch of which device went into which patient.

    Recording one is a single act: the device leaves the shelf *and* the
    trace is written, in one transaction. Splitting them would allow a
    trace with no movement behind it — a device nobody took — or stock
    that left with nobody carrying it.
    """

    @staticmethod
    async def list(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        patient_id: UUID | None = None,
        lot_id: UUID | None = None,
        item_id: UUID | None = None,
    ) -> list[ImplantTrace]:
        filters = [ImplantTrace.clinic_id == clinic_id]
        if patient_id:
            filters.append(ImplantTrace.patient_id == patient_id)
        if lot_id:
            filters.append(ImplantTrace.lot_id == lot_id)
        if item_id:
            filters.append(ImplantTrace.item_id == item_id)
        rows = await db.execute(
            select(ImplantTrace)
            .options(joinedload(ImplantTrace.item), joinedload(ImplantTrace.lot))
            .where(*filters)
            .order_by(ImplantTrace.placed_on.desc())
        )
        return list(rows.unique().scalars().all())

    @staticmethod
    async def record(
        db: AsyncSession, clinic_id: UUID, user_id: UUID | None, data: dict
    ) -> ImplantTrace:
        """Take one device off the shelf and record who carries it."""
        item = await ItemService.get(db, clinic_id, data["item_id"])
        if item is None:
            raise InventoryError("Article not found")
        if not item.tracks_lots:
            raise InventoryError(
                "An implantable device must track lots: there is nothing to trace otherwise"
            )

        lot = await LotService.get(db, clinic_id, data["lot_id"])
        if lot is None or lot.item_id != item.id:
            raise InventoryError("Lot not found for this article")

        location_id = data.get("location_id") or await LocationService.default_id(db, clinic_id)
        movement = await StockService.post(
            db,
            clinic_id,
            user_id,
            item_id=item.id,
            location_id=location_id,
            lot_id=lot.id,
            quantity_base=Decimal(data.get("quantity") or 1),
            reason="consumption",
            note=data.get("notes"),
            # Opaque, like every other cause (ADR 0039): the ledger does
            # not know what an implant trace is.
            source_ref={"kind": "implant", "id": str(data["patient_id"])},
        )

        trace = ImplantTrace(
            clinic_id=clinic_id,
            patient_id=data["patient_id"],
            item_id=item.id,
            lot_id=lot.id,
            movement_id=movement.id,
            placed_on=data["placed_on"],
            tooth_number=data.get("tooth_number"),
            serial_number=data.get("serial_number"),
            professional_id=data.get("professional_id"),
            notes=data.get("notes"),
        )
        db.add(trace)
        await db.flush()
        return trace


class MaterialService:
    """What each catalogue treatment is expected to consume.

    Keyed by ``catalog_item_id`` with no foreign key: the Treatments App
    may be off, and this list is the inventory's own (see the model).
    Nothing here reads the catalogue — the router adds the names through
    the ``TreatmentCatalogue`` contract when there is one.
    """

    @staticmethod
    async def list(
        db: AsyncSession, clinic_id: UUID, *, catalog_item_id: UUID | None = None
    ) -> list[TreatmentMaterial]:
        filters = [TreatmentMaterial.clinic_id == clinic_id]
        if catalog_item_id:
            filters.append(TreatmentMaterial.catalog_item_id == catalog_item_id)
        rows = await db.execute(
            select(TreatmentMaterial).options(joinedload(TreatmentMaterial.item)).where(*filters)
        )
        return list(rows.unique().scalars().all())

    @staticmethod
    async def set_for_treatment(
        db: AsyncSession, clinic_id: UUID, catalog_item_id: UUID, lines: list[dict]
    ) -> list[TreatmentMaterial]:
        """Replace a treatment's whole list.

        A whole-list write rather than per-row edits: the screen shows
        the list as one thing, and a partial update would need an order
        of operations nobody would get right from the UI.
        """
        existing = await MaterialService.list(db, clinic_id, catalog_item_id=catalog_item_id)
        for row in existing:
            await db.delete(row)
        await db.flush()

        for line in lines:
            item = await ItemService.get(db, clinic_id, line["item_id"])
            if item is None:
                raise InventoryError("Article not found")
            quantity = Decimal(line["quantity_base"]).quantize(QUANTITY_STEP)
            if quantity <= ZERO:
                raise InventoryError("A material line needs a positive quantity")
            db.add(
                TreatmentMaterial(
                    clinic_id=clinic_id,
                    catalog_item_id=catalog_item_id,
                    item_id=item.id,
                    quantity_base=quantity,
                )
            )
        await db.flush()
        return await MaterialService.list(db, clinic_id, catalog_item_id=catalog_item_id)


class StockService:
    """The ledger, the snapshot, and everything read from them."""

    # --- writing ------------------------------------------------------

    @staticmethod
    async def post(
        db: AsyncSession,
        clinic_id: UUID,
        user_id: UUID | None,
        *,
        item_id: UUID,
        location_id: UUID | None,
        lot_id: UUID | None,
        quantity_base: Decimal,
        reason: str,
        note: str | None = None,
        cost_per_base_unit: Decimal | None = None,
        source_ref: dict | None = None,
    ) -> InventoryMovement:
        """Append one movement and move its level by the same amount.

        The only way stock changes. Returns the movement; the caller does
        not commit (``commit_before_response``, ADR 0031).
        """
        item = await ItemService.get(db, clinic_id, item_id)
        if item is None:
            raise InventoryError("Article not found")

        quantity = StockService._signed(reason, quantity_base)
        if quantity == ZERO:
            raise InventoryError("A movement of zero changes nothing")

        if location_id is None:
            location_id = await LocationService.default_id(db, clinic_id)
        location = await LocationService.get(db, clinic_id, location_id)
        if location is None:
            raise InventoryError("Location not found")
        if location.status != "active":
            raise InventoryError("That location is archived")

        if item.tracks_lots:
            if lot_id is None:
                raise InventoryError("This article tracks lots: name the lot")
            lot = await LotService.get(db, clinic_id, lot_id)
            if lot is None or lot.item_id != item_id:
                raise InventoryError("Lot not found for this article")
        elif lot_id is not None:
            raise InventoryError("This article does not track lots")

        level = await StockService._locked_level(db, clinic_id, item_id, location_id, lot_id)
        resulting = Decimal(level.quantity) + quantity
        if resulting < ZERO and reason != ADJUSTMENT_REASON:
            raise InventoryError(
                f"Not enough stock: {level.quantity} {item.base_unit} on hand, "
                f"{abs(quantity)} requested"
            )

        level.quantity = resulting
        # What this quantity cost, stamped at the moment it moved. A
        # receipt brings its own price; anything leaving is costed at the
        # article's weighted average *now*, because a report run next
        # year must say what the material cost then, not what it costs
        # today. Movements recorded before this existed keep their null,
        # and the figures that read them say so.
        if cost_per_base_unit is None and item.cost_per_base_unit is not None:
            cost_per_base_unit = Decimal(item.cost_per_base_unit)
        movement = InventoryMovement(
            clinic_id=clinic_id,
            item_id=item_id,
            location_id=location_id,
            lot_id=lot_id,
            quantity_base=quantity,
            reason=reason,
            note=note,
            cost_per_base_unit=cost_per_base_unit,
            source_ref=source_ref,
            performed_by=user_id,
        )
        db.add(movement)
        await db.flush()

        event_bus.publish_after_commit(
            db,
            EventType.INVENTORY_MOVEMENT_RECORDED,
            {
                "clinic_id": str(clinic_id),
                "movement_id": str(movement.id),
                "item_id": str(item_id),
                "location_id": str(location_id),
                "lot_id": str(lot_id) if lot_id else None,
                "quantity_base": str(quantity),
                "reason": reason,
            },
        )
        await StockService._announce_shortage(db, clinic_id, item)
        return movement

    @staticmethod
    async def transfer(
        db: AsyncSession, clinic_id: UUID, user_id: UUID | None, data: dict
    ) -> list[InventoryMovement]:
        """Move stock between locations: two movements, one transaction.

        They share a ``source_ref`` so the pair can be read back as one
        act. A transfer is never an update of two levels — that would
        leave the ledger unable to explain either of them.
        """
        if data["from_location_id"] == data["to_location_id"]:
            raise InventoryError("A transfer needs two different locations")

        marker = {"kind": "transfer", "id": str(uuid7())}
        out = await StockService.post(
            db,
            clinic_id,
            user_id,
            item_id=data["item_id"],
            location_id=data["from_location_id"],
            lot_id=data.get("lot_id"),
            quantity_base=-abs(data["quantity_base"]),
            reason="transfer",
            note=data.get("note"),
            source_ref=marker,
        )
        incoming = await StockService.post(
            db,
            clinic_id,
            user_id,
            item_id=data["item_id"],
            location_id=data["to_location_id"],
            lot_id=data.get("lot_id"),
            quantity_base=abs(data["quantity_base"]),
            reason="transfer",
            note=data.get("note"),
            source_ref=marker,
        )
        return [out, incoming]

    @staticmethod
    async def count(db: AsyncSession, clinic_id: UUID, user_id: UUID | None, data: dict) -> dict:
        """Close a physical count: post the differences as adjustments.

        A line that agrees with the snapshot posts nothing. A line that
        disagrees posts the difference with the counter's note, so
        afterwards the record holds both what was believed and what was
        found.
        """
        posted: list[UUID] = []
        note = data.get("note") or "Recuento físico"
        for line in data["lines"]:
            level = await StockService._locked_level(
                db, clinic_id, line["item_id"], line["location_id"], line.get("lot_id")
            )
            difference = Decimal(line["counted_quantity"]) - Decimal(level.quantity)
            if difference == ZERO:
                continue
            movement = await StockService.post(
                db,
                clinic_id,
                user_id,
                item_id=line["item_id"],
                location_id=line["location_id"],
                lot_id=line.get("lot_id"),
                quantity_base=difference,
                reason=ADJUSTMENT_REASON,
                note=note,
                source_ref={"kind": "count", "counted": str(line["counted_quantity"])},
            )
            posted.append(movement.id)
        return {
            "lines_counted": len(data["lines"]),
            "adjustments_posted": len(posted),
            "movement_ids": posted,
        }

    # --- reading ------------------------------------------------------

    @staticmethod
    async def movements(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        item_id: UUID | None = None,
        location_id: UUID | None = None,
        reason: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> tuple[list[InventoryMovement], int]:
        filters = [InventoryMovement.clinic_id == clinic_id]
        if item_id:
            filters.append(InventoryMovement.item_id == item_id)
        if location_id:
            filters.append(InventoryMovement.location_id == location_id)
        if reason:
            filters.append(InventoryMovement.reason == reason)
        if date_from:
            filters.append(
                InventoryMovement.created_at >= datetime.combine(date_from, datetime.min.time())
            )
        if date_to:
            filters.append(
                InventoryMovement.created_at <= datetime.combine(date_to, datetime.max.time())
            )

        total = await db.scalar(select(func.count()).select_from(InventoryMovement).where(*filters))
        rows = await db.execute(
            select(InventoryMovement)
            .options(
                joinedload(InventoryMovement.item),
                joinedload(InventoryMovement.location),
                joinedload(InventoryMovement.lot),
                joinedload(InventoryMovement.performer),
            )
            .where(*filters)
            .order_by(InventoryMovement.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.unique().scalars().all()), int(total or 0)

    @staticmethod
    async def get_movement(
        db: AsyncSession, clinic_id: UUID, movement_id: UUID
    ) -> InventoryMovement | None:
        """One ledger line with the names a response needs loaded."""
        return await db.scalar(
            select(InventoryMovement)
            .options(
                joinedload(InventoryMovement.item),
                joinedload(InventoryMovement.location),
                joinedload(InventoryMovement.lot),
                joinedload(InventoryMovement.performer),
            )
            .where(
                InventoryMovement.id == movement_id,
                InventoryMovement.clinic_id == clinic_id,
            )
        )

    @staticmethod
    async def levels(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        item_id: UUID | None = None,
        location_id: UUID | None = None,
        category: str | None = None,
        search: str | None = None,
        include_empty: bool = False,
    ) -> list[dict]:
        """The stock screen's rows, with each article's total alongside.

        The total is the figure a reorder decision is taken from: one
        cabinet being empty says nothing about whether to buy more.
        """
        filters = [InventoryStockLevel.clinic_id == clinic_id, InventoryItem.status == "active"]
        if item_id:
            filters.append(InventoryStockLevel.item_id == item_id)
        if location_id:
            filters.append(InventoryStockLevel.location_id == location_id)
        if category:
            filters.append(InventoryItem.category == category)
        if search:
            pattern = f"%{search.strip()}%"
            filters.append(InventoryItem.name.ilike(pattern) | InventoryItem.code.ilike(pattern))
        if not include_empty:
            filters.append(InventoryStockLevel.quantity != 0)

        rows = await db.execute(
            select(InventoryStockLevel, InventoryItem, InventoryLocation, InventoryLot)
            .join(InventoryItem, InventoryStockLevel.item_id == InventoryItem.id)
            .join(InventoryLocation, InventoryStockLevel.location_id == InventoryLocation.id)
            .outerjoin(InventoryLot, InventoryStockLevel.lot_id == InventoryLot.id)
            .where(*filters)
            .order_by(InventoryItem.name, InventoryLocation.name)
        )
        found = list(rows.all())

        totals = await StockService.item_totals(
            db, clinic_id, [level.item_id for level, _, _, _ in found]
        )
        today = datetime.now(UTC).date()
        return [
            {
                "item_id": level.item_id,
                "item_code": item.code,
                "item_name": item.name,
                "category": item.category,
                "base_unit": item.base_unit,
                "location_id": level.location_id,
                "location_name": location.name,
                "lot_id": level.lot_id,
                "lot_code": lot.lot_code if lot else None,
                "expires_on": lot.expires_on if lot else None,
                "quantity": Decimal(level.quantity),
                "item_total": totals.get(level.item_id, ZERO),
                "reorder_point": item.reorder_point,
                "is_low": StockService._is_low(item, totals.get(level.item_id, ZERO)),
                "days_to_expiry": (
                    (lot.expires_on - today).days if lot and lot.expires_on else None
                ),
            }
            for level, item, location, lot in found
        ]

    @staticmethod
    async def item_totals(
        db: AsyncSession, clinic_id: UUID, item_ids: list[UUID] | None = None
    ) -> dict[UUID, Decimal]:
        """On-hand per article across every location and lot."""
        query = (
            select(
                InventoryStockLevel.item_id,
                func.coalesce(func.sum(InventoryStockLevel.quantity), 0),
            )
            .where(InventoryStockLevel.clinic_id == clinic_id)
            .group_by(InventoryStockLevel.item_id)
        )
        if item_ids:
            query = query.where(InventoryStockLevel.item_id.in_(set(item_ids)))
        rows = await db.execute(query)
        return {item_id: Decimal(total) for item_id, total in rows.all()}

    @staticmethod
    async def alerts(
        db: AsyncSession, clinic_id: UUID, *, window_days: int = EXPIRY_WINDOW_DAYS
    ) -> dict:
        """What needs attention: low stock, expiring soon, already expired."""
        lines = await StockService.levels(db, clinic_id, include_empty=True)
        today = datetime.now(UTC).date()
        low: dict[UUID, dict] = {}
        expiring: list[dict] = []
        expired: list[dict] = []
        for line in lines:
            if line["is_low"] and line["item_id"] not in low:
                low[line["item_id"]] = line
            days = line["days_to_expiry"]
            if days is None or line["quantity"] <= ZERO:
                continue
            if days < 0:
                expired.append(line)
            elif days <= window_days:
                expiring.append(line)
        expiring.sort(key=lambda line: line["days_to_expiry"])
        expired.sort(key=lambda line: line["days_to_expiry"])
        _ = today
        return {"low_stock": list(low.values()), "expiring": expiring, "expired": expired}

    @staticmethod
    async def reconcile(db: AsyncSession, clinic_id: UUID) -> dict:
        """Recompute every level from the ledger (ADR 0065).

        ``corrected`` is expected to be zero. Anything else is a write
        that reached ``inv_stock_levels`` outside :meth:`post`.
        """
        ledger = await db.execute(
            select(
                InventoryMovement.item_id,
                InventoryMovement.location_id,
                InventoryMovement.lot_id,
                func.sum(InventoryMovement.quantity_base),
            )
            .where(InventoryMovement.clinic_id == clinic_id)
            .group_by(
                InventoryMovement.item_id,
                InventoryMovement.location_id,
                InventoryMovement.lot_id,
            )
        )
        truth = {
            (item_id, location_id, lot_id): Decimal(total)
            for item_id, location_id, lot_id, total in ledger.all()
        }
        rows = await db.execute(
            select(InventoryStockLevel).where(InventoryStockLevel.clinic_id == clinic_id)
        )
        levels = list(rows.scalars().all())

        corrected = removed = 0
        seen: set[tuple] = set()
        for level in levels:
            key = (level.item_id, level.location_id, level.lot_id)
            seen.add(key)
            expected = truth.get(key)
            if expected is None:
                # A level with no ledger behind it cannot be right, but it
                # is still stock somebody may be holding: zero it rather
                # than delete it, so the row keeps saying where it was.
                if Decimal(level.quantity) != ZERO:
                    level.quantity = ZERO
                    removed += 1
                continue
            if Decimal(level.quantity) != expected:
                level.quantity = expected
                corrected += 1
        for key, expected in truth.items():
            if key in seen:
                continue
            item_id, location_id, lot_id = key
            db.add(
                InventoryStockLevel(
                    clinic_id=clinic_id,
                    item_id=item_id,
                    location_id=location_id,
                    lot_id=lot_id,
                    quantity=expected,
                )
            )
            corrected += 1
        await db.flush()
        return {
            "levels_checked": len(levels),
            "corrected": corrected,
            "removed": removed,
        }

    # --- internals ----------------------------------------------------

    @staticmethod
    def _signed(reason: str, quantity: Decimal) -> Decimal:
        """Apply the sign the reason implies, at the ledger's scale.

        An adjustment and a transfer carry their own sign; every other
        reason knows which way stock went, and asking the caller to agree
        with it is how a receipt ends up subtracting.
        """
        quantity = Decimal(quantity).quantize(QUANTITY_STEP)
        if reason in _SIGNED_BY_CALLER:
            return quantity
        if quantity <= ZERO:
            raise InventoryError(f"A '{reason}' movement needs a positive quantity")
        return quantity if reason in _INCOMING else -quantity

    @staticmethod
    def _is_low(item: InventoryItem, total: Decimal) -> bool:
        if item.reorder_point is None:
            return False
        return total <= Decimal(item.reorder_point)

    @staticmethod
    async def _locked_level(
        db: AsyncSession,
        clinic_id: UUID,
        item_id: UUID,
        location_id: UUID,
        lot_id: UUID | None,
    ) -> InventoryStockLevel:
        """The level row for this triple, locked, creating it if absent.

        ``FOR UPDATE`` serializes two people consuming the same article at
        once; without it both read the same quantity and the second write
        silently discards the first. The insert races against another
        process doing the same thing, so the unique violation is caught in
        a savepoint and the row re-read — the alternative is a 500 the
        first time two cabinets consume gloves in the same second.
        """
        level = await db.scalar(
            select(InventoryStockLevel)
            .where(*_level_match(item_id, location_id, lot_id))
            .with_for_update()
        )
        if level is not None:
            return level
        try:
            async with db.begin_nested():
                level = InventoryStockLevel(
                    clinic_id=clinic_id,
                    item_id=item_id,
                    location_id=location_id,
                    lot_id=lot_id,
                    quantity=ZERO,
                )
                db.add(level)
                await db.flush()
            return level
        except IntegrityError:
            found = await db.scalar(
                select(InventoryStockLevel)
                .where(*_level_match(item_id, location_id, lot_id))
                .with_for_update()
            )
            if found is None:  # pragma: no cover - only if the constraint changed
                raise
            return found

    @staticmethod
    async def _announce_shortage(db: AsyncSession, clinic_id: UUID, item: InventoryItem) -> None:
        """Say so when this movement took an article to or below its point.

        Published from the write rather than only from the daily job
        because the useful moment is the one where the last box left the
        shelf. The daily job is the safety net for stock that was already
        low when the point was set.
        """
        totals = await StockService.item_totals(db, clinic_id, [item.id])
        total = totals.get(item.id, ZERO)
        if total <= ZERO:
            event_bus.publish_after_commit(
                db,
                EventType.INVENTORY_STOCK_OUT,
                {
                    "clinic_id": str(clinic_id),
                    "item_id": str(item.id),
                    "item_name": item.name,
                },
            )
        if StockService._is_low(item, total):
            event_bus.publish_after_commit(
                db,
                EventType.INVENTORY_STOCK_LOW,
                {
                    "clinic_id": str(clinic_id),
                    "item_id": str(item.id),
                    "item_name": item.name,
                    "on_hand": str(total),
                    "reorder_point": str(item.reorder_point),
                    "reorder_quantity": (
                        str(item.reorder_quantity) if item.reorder_quantity else None
                    ),
                },
            )
            item.low_stock_notified_at = datetime.now(UTC)
