"""What the inventory does when a treatment is carried out.

This is the whole of layer 3's mechanism: the clinic finishes a treatment, the
Treatments App says so, and the material that treatment is expected to
use leaves the shelf — as ordinary movements in the ledger (ADR 0065),
with a ``source_ref`` naming the planned item that caused them.

Three decisions worth knowing before changing anything here:

1. **The coupling runs inward.** Nothing publishes *at* the inventory on
   purpose: `treatment_plan` announces a fact about its own world and
   knows nothing about stock. Switch this module off and the event goes
   unanswered, which is not a refusal (ADR 0064).

2. **Posting is idempotent per planned item.** Events get redelivered,
   and an item can be reopened and completed again; the material was
   used once. A second attempt for the same ``source_ref`` does nothing.

3. **A shortfall is never invented.** If the shelf says there is less
   than the treatment needs, what is there is consumed and the movement
   says how much was missing. The alternative — writing a negative, or
   refusing the clinical fact — either breaks the ledger's invariant or
   throws away what actually happened. The discrepancy is what a
   physical count exists to settle.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker

from .integrations import planned_treatments
from .models import InventoryMovement, TreatmentMaterial
from .service import InventoryError, LocationService, StockService

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

#: What marks a movement as "this treatment's automatic consumption".
SOURCE_KIND = "treatment_item"


async def on_treatment_completed(data: dict) -> None:
    """Consume what the completed treatment is expected to have used.

    The bus calls a handler with the payload and nothing else, and runs
    it after the publisher's transaction committed (ADR 0019). So the
    session is this handler's own, opened here and committed here — a
    handler that took one as an argument would look fine in a unit test
    and fail in production with
    ``missing 1 required positional argument: 'db'``, which is exactly
    what it did.
    """
    async with async_session_maker() as db:
        await consume_for_treatment(data, db)
        await db.commit()


async def consume_for_treatment(data: dict, db: AsyncSession) -> None:
    """The work itself, against a caller-supplied session."""
    clinic_id = UUID(str(data["clinic_id"]))
    item_id = UUID(str(data["item_id"]))

    directory = planned_treatments()
    if directory is None:
        # The Treatments App is off, which is possible even though it is
        # what published this: the handler can outlive the publisher in a
        # process that is being reconfigured.
        return

    catalog_item_id = (await directory.catalog_item_ids(db, clinic_id, [item_id])).get(item_id)
    if catalog_item_id is None:
        # A planned item with no catalogue treatment behind it — added
        # free-hand, or from the odontogram without a catalogue link.
        # Nothing says what it consumes.
        return

    materials = await materials_for(db, clinic_id, catalog_item_id)
    if not materials:
        return

    if await already_consumed(db, clinic_id, item_id):
        return

    location_id = await LocationService.default_id(db, clinic_id)
    for material in materials:
        await _consume(db, clinic_id, data, material, location_id, item_id)


async def materials_for(
    db: AsyncSession, clinic_id: UUID, catalog_item_id: UUID
) -> list[TreatmentMaterial]:
    rows = await db.execute(
        select(TreatmentMaterial).where(
            TreatmentMaterial.clinic_id == clinic_id,
            TreatmentMaterial.catalog_item_id == catalog_item_id,
        )
    )
    return list(rows.scalars().all())


async def already_consumed(db: AsyncSession, clinic_id: UUID, item_id: UUID) -> bool:
    """Whether this planned item already took its material off the shelf."""
    found = await db.scalar(
        select(InventoryMovement.id).where(
            InventoryMovement.clinic_id == clinic_id,
            InventoryMovement.source_ref["kind"].astext == SOURCE_KIND,
            InventoryMovement.source_ref["id"].astext == str(item_id),
        )
    )
    return found is not None


async def _consume(
    db: AsyncSession,
    clinic_id: UUID,
    data: dict,
    material: TreatmentMaterial,
    location_id: UUID,
    item_id: UUID,
) -> None:
    wanted = Decimal(material.quantity_base)
    on_hand = (await StockService.item_totals(db, clinic_id, [material.item_id])).get(
        material.item_id, ZERO
    )
    quantity = min(wanted, on_hand)
    if quantity <= ZERO:
        logger.warning(
            "inventory: nothing on hand of %s for treatment item %s (wanted %s)",
            material.item_id,
            item_id,
            wanted,
        )
        return

    note = str(data.get("item_name") or "")
    if quantity < wanted:
        note = f"{note} — faltaban {wanted - quantity}".strip(" —")

    try:
        await StockService.post(
            db,
            clinic_id,
            _user_id(data),
            item_id=material.item_id,
            location_id=location_id,
            # Lot-tracked material cannot be chosen automatically: which
            # batch was opened is a fact only the person at the chair
            # knows. Those articles are recorded by hand.
            lot_id=None,
            quantity_base=quantity,
            reason="consumption",
            note=note or None,
            source_ref={"kind": SOURCE_KIND, "id": str(item_id)},
        )
    except InventoryError as exc:
        # The commonest case is an article that tracks lots. Refusing the
        # whole handler over it would lose the rest of the treatment's
        # material, so it is logged and skipped.
        logger.warning(
            "inventory: could not consume %s for treatment item %s: %s",
            material.item_id,
            item_id,
            exc,
        )


def _user_id(data: dict) -> UUID | None:
    raw = data.get("completed_by")
    return UUID(str(raw)) if raw else None
