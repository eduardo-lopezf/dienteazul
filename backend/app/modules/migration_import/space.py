"""Whether what a migration is about to write fits in the clinic's storage.

The clinic's limit (its tier's, or its own: ``app.core.auth.limits``) holds
every upload already; a migration writes in bulk and by other paths — the
file it is given, the documents a ``.dpm`` carries, the copy an export
leaves on the server — so it asks before starting, and says how much it
needs and how much is left.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.limits import clinic_limits
from app.core.tenancy import TenantContext

from .errors import migration_error

_MB = 1024 * 1024


def megabytes(size: int) -> str:
    return f"{size / _MB:.1f} MB"


async def free_bytes(db: AsyncSession, tenant: TenantContext, clinic_id: UUID) -> int | None:
    """What is left of the clinic's storage; ``None`` when it has no limit."""
    limits = await clinic_limits(db, tenant, clinic_id)
    if limits.storage_limit_bytes is None:
        return None
    return max(limits.storage_limit_bytes - limits.storage_bytes, 0)


async def ensure_room(
    db: AsyncSession, tenant: TenantContext, clinic_id: UUID, needed: int, what: str
) -> None:
    """Refuse — before anything is written — what does not fit."""
    if needed <= 0:
        return
    free = await free_bytes(db, tenant, clinic_id)
    if free is not None and needed > free:
        raise migration_error(
            "migration_import.storage.insufficient_space",
            detail=(
                f"No hay espacio suficiente para {what}: hacen falta {megabytes(needed)} y quedan "
                f"{megabytes(free)} en el espacio de la clínica. Libera espacio o amplía el plan."
            ),
        )
