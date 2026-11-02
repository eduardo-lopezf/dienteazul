"""What the inventory offers other modules without being imported.

This is the module's **only** outward contract, and the first time
anything flows out of it at all. Everything else about the inventory is
read inward — catalogue names, planned treatments, patient names — which
is what keeps the App switchable.

`reports` consumes this one. The rule that makes that safe is the same
as everywhere else: it asks the core for a supplier, and `None` means
the Inventario App is off, so Productividad shows the rest of its
figures and leaves this one out (ADR 0037, ADR 0039).

The figures come from the ledger's own ``cost_per_base_unit``, stamped
on each movement when it happened, so a report of last March says what
the material cost in March (ADR 0065).
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import MaterialCostLine

from .events import SOURCE_KIND
from .integrations import planned_treatments
from .models import InventoryMovement

ZERO = Decimal("0")
MONEY = Decimal("0.01")

#: Reasons that mean "it left the shelf and was used or lost". A
#: transfer moves stock between locations and costs the clinic nothing,
#: and an adjustment is a correction, not a consumption — counting
#: either as cost would make the figure a fiction.
CONSUMING_REASONS = ("consumption", "expiry_write_off")


def _window(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    return datetime.combine(date_from, time.min), datetime.combine(date_to, time.max)


def _cost_of(movement: InventoryMovement) -> Decimal:
    """What one movement cost, or zero when nothing was ever priced.

    A movement recorded before the ledger stamped outgoing costs, or of
    an article whose cost the clinic never entered, contributes nothing
    rather than a guess. The report says how much of the period that is.
    """
    if movement.cost_per_base_unit is None:
        return ZERO
    return (abs(Decimal(movement.quantity_base)) * Decimal(movement.cost_per_base_unit)).quantize(
        MONEY
    )


class InventoryMaterialCost:
    async def by_treatment(
        self, db: AsyncSession, clinic_id: UUID, date_from: date, date_to: date
    ) -> list[MaterialCostLine]:
        start, end = _window(date_from, date_to)
        rows = await db.execute(
            select(InventoryMovement).where(
                InventoryMovement.clinic_id == clinic_id,
                InventoryMovement.reason.in_(CONSUMING_REASONS),
                InventoryMovement.created_at >= start,
                InventoryMovement.created_at <= end,
                InventoryMovement.source_ref["kind"].astext == SOURCE_KIND,
            )
        )
        movements = list(rows.scalars().all())
        if not movements:
            return []

        # The ledger knows the planned item that caused each movement,
        # not the treatment type. Resolving one to the other belongs to
        # the Treatments App, so it is asked rather than joined — and
        # with that App off every line simply groups under `None`.
        planned_ids = {
            UUID(movement.source_ref["id"])
            for movement in movements
            if movement.source_ref and movement.source_ref.get("id")
        }
        directory = planned_treatments()
        catalogue_of = (
            await directory.catalog_item_ids(db, clinic_id, planned_ids) if directory else {}
        )

        totals: dict[UUID | None, Decimal] = {}
        seen: dict[UUID | None, set[UUID]] = {}
        unpriced: dict[UUID | None, int] = {}
        for movement in movements:
            planned_id = UUID(movement.source_ref["id"])
            key = catalogue_of.get(planned_id)
            totals[key] = totals.get(key, ZERO) + _cost_of(movement)
            seen.setdefault(key, set()).add(planned_id)
            if movement.cost_per_base_unit is None:
                unpriced[key] = unpriced.get(key, 0) + 1

        return sorted(
            (
                MaterialCostLine(
                    catalog_item_id=key,
                    treatments=len(seen[key]),
                    cost=totals[key],
                    unpriced=unpriced.get(key, 0),
                )
                for key in totals
            ),
            key=lambda line: line.cost,
            reverse=True,
        )

    async def consumed_total(
        self, db: AsyncSession, clinic_id: UUID, date_from: date, date_to: date
    ) -> Decimal:
        start, end = _window(date_from, date_to)
        total = await db.scalar(
            select(
                func.coalesce(
                    func.sum(
                        func.abs(InventoryMovement.quantity_base)
                        * InventoryMovement.cost_per_base_unit
                    ),
                    0,
                )
            ).where(
                InventoryMovement.clinic_id == clinic_id,
                InventoryMovement.reason.in_(CONSUMING_REASONS),
                InventoryMovement.created_at >= start,
                InventoryMovement.created_at <= end,
                InventoryMovement.cost_per_base_unit.is_not(None),
            )
        )
        return Decimal(total or 0).quantize(MONEY)


material_cost = InventoryMaterialCost()
