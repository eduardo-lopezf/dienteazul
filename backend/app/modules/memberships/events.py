"""What memberships does when a fee's payment is refunded."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.database import async_session_maker

from .service import MembershipService

logger = logging.getLogger(__name__)


async def on_payment_refunded(data: dict[str, Any]) -> None:
    """``payment.refunded``: a fee refunded in full leaves its period uncovered.

    Payments of anything else are not this module's and find no period.
    """
    try:
        clinic_id = UUID(str(data["clinic_id"]))
        payment_id = UUID(str(data["payment_id"]))
        amount = Decimal(str(data["amount"]))
    except (KeyError, ValueError, TypeError, InvalidOperation):
        logger.debug("payment.refunded: missing fields (data=%s)", data)
        return
    async with async_session_maker() as db:
        try:
            await MembershipService.fee_refunded(db, clinic_id, payment_id, amount)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
