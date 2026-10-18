"""What the professionals module does when a clinic is made or moved.

An individual practice (``INDIVIDUAL_TIERS``) gets its holder's profile on
the day it exists — patients, treatments and appointments are assigned to
them from the start — and the same when an operator moves a clinic to an
individual tier. ``HolderProfileService.ensure`` is idempotent, so either
event arriving twice changes nothing.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.database import async_session_maker

from .service import HolderProfileService

logger = logging.getLogger(__name__)


async def _ensure_holder_profile(data: dict[str, Any], event: str) -> None:
    try:
        clinic_id = UUID(str(data["clinic_id"]))
    except (KeyError, ValueError, TypeError):
        return
    async with async_session_maker() as db:
        profile = await HolderProfileService.ensure(db, clinic_id)
        await db.commit()
    if profile is not None:
        logger.info("professionals: holder profile ready for clinic %s (%s)", clinic_id, event)


async def on_clinic_created(data: dict[str, Any]) -> None:
    await _ensure_holder_profile(data, "clinic.created")


async def on_clinic_account_tier_changed(data: dict[str, Any]) -> None:
    await _ensure_holder_profile(data, "clinic.account_tier_changed")
