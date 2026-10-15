"""Periodic work of the migration App. Declared in ``get_scheduled_jobs``:
only the process that runs the scheduler runs it (ADR 0051)."""

from __future__ import annotations

import logging

from app.database import async_session_maker

from .export import ExportJobService

logger = logging.getLogger(__name__)


async def expire_exports() -> None:
    """Remove the export files past their retention."""
    async with async_session_maker() as db:
        expired = await ExportJobService.expire_old(db)
        await db.commit()
    if expired:
        logger.info("migration_import: %d export file(s) expired", expired)
