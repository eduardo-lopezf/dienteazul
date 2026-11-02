"""What the material the clinic used actually cost.

Read from the Inventario App through the ``MaterialCost`` contract —
never by importing it. A clinic can switch that App off, and
Productividad has to go on showing every other figure (ADR 0037,
ADR 0039); the route is guarded with ``needs("inventory")`` so the
section disappears instead of breaking.

The cost of a treatment type is not its price: it is what left the shelf
against it, at what the ledger says that material cost when it moved.
Comparing the two is the point of the report.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import MaterialCost, TreatmentCatalogue, provider

from ..integrations import NO_NAME

ZERO = Decimal("0")


def _localized(names: dict[str, str]) -> str:
    return names.get("es") or names.get("en") or next(iter(names.values()), NO_NAME)


class MaterialCostReportService:
    @staticmethod
    async def by_treatment(
        db: AsyncSession, clinic_id: UUID, date_from: date, date_to: date
    ) -> dict:
        """Material cost per treatment type, most expensive first.

        Two Apps are read and both may be off: the inventory supplies
        the figures, the catalogue supplies the names. Without the
        catalogue the figures stay and the names go — the same rule the
        rest of this module follows.
        """
        costs: MaterialCost | None = provider(MaterialCost)
        if costs is None:  # pragma: no cover - the route guard answers first
            return {"total": ZERO, "unpriced_note": False, "lines": []}

        lines = await costs.by_treatment(db, clinic_id, date_from, date_to)
        catalogue: TreatmentCatalogue | None = provider(TreatmentCatalogue)
        briefs = (
            await catalogue.briefs(
                db, clinic_id, [line.catalog_item_id for line in lines if line.catalog_item_id]
            )
            if catalogue and lines
            else {}
        )

        return {
            "total": await costs.consumed_total(db, clinic_id, date_from, date_to),
            # True when any material consumed had no price on file.
            # Counted per movement, not per line: a line can total a
            # real figure and still be missing half its material, and a
            # zero that reads as "free" is the one thing this figure
            # must never do.
            "unpriced_note": any(line.unpriced for line in lines),
            "lines": [
                {
                    "catalog_item_id": line.catalog_item_id,
                    "treatment_name": (
                        _localized(briefs[line.catalog_item_id].names)
                        if line.catalog_item_id in briefs
                        else NO_NAME
                    ),
                    "treatments": line.treatments,
                    "cost": line.cost,
                    "cost_per_treatment": (
                        (line.cost / line.treatments).quantize(Decimal("0.01"))
                        if line.treatments
                        else ZERO
                    ),
                }
                for line in lines
            ],
        }
