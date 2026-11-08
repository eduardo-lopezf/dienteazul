"""What commissions does when a clinic switches it on (ADR 0066).

It becomes the clinic's only source of percentages at that moment, so the
ones agreed in `liquidations` are carried over first — only for
professionals with no agreement here, so switching it off and on again
keeps what was set here and changes nothing else.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.database import async_session_maker

from .service import adopt_liquidation_percentages

logger = logging.getLogger(__name__)


async def on_clinic_module_enabled(data: dict[str, Any]) -> None:
    if data.get("module") != "commissions":
        return
    try:
        clinic_id = UUID(str(data["clinic_id"]))
    except (KeyError, ValueError, TypeError):
        return
    async with async_session_maker() as db:
        adopted = await adopt_liquidation_percentages(db, clinic_id)
        await db.commit()
    logger.info("commissions: adopted %d percentages for clinic %s", adopted, clinic_id)
