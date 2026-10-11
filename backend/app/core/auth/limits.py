"""What a clinic's account tier allows it, and the refusals that hold it.

The limits are per tier (``tier_limits``) and set by the control plane; a
tier with none is unlimited. Two things are held: the users a clinic adds
besides its holder, and the disk its uploaded files take.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.tenancy import TenantContext, get_tenant
from app.core.tenancy.usage import file_usage
from app.database import get_db

from .dependencies import ClinicContext, get_clinic_context
from .models import Clinic, ClinicMembership, TierLimit

_MB = 1024 * 1024

USER_LIMIT_REACHED = "User limit reached"
STORAGE_LIMIT_REACHED = "Storage limit reached"


@dataclass(frozen=True, slots=True)
class ClinicLimits:
    users: int
    #: The holder and the users the tier lets it add; ``None`` is no limit.
    users_limit: int | None
    storage_bytes: int
    storage_limit_bytes: int | None


async def _tier_limit(db: AsyncSession, clinic_id: UUID) -> TierLimit | None:
    return await db.scalar(
        select(TierLimit)
        .join(Clinic, Clinic.account_tier == TierLimit.tier)
        .where(Clinic.id == clinic_id)
    )


async def _users(db: AsyncSession, clinic_id: UUID) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(ClinicMembership)
        .where(ClinicMembership.clinic_id == clinic_id)
    )


async def _storage_bytes(tenant: TenantContext, clinic_id: UUID) -> int:
    # Files are stored under ``<clinic_id>/…``. Walked each time: a folder
    # held to tens of megabytes is small, and a cached figure would let
    # uploads through after the limit.
    root = Path(settings.STORAGE_LOCAL_PATH) / tenant.storage_prefix / str(clinic_id)
    return (await asyncio.to_thread(file_usage, root)).total_bytes


async def clinic_limits(db: AsyncSession, tenant: TenantContext, clinic_id: UUID) -> ClinicLimits:
    limit = await _tier_limit(db, clinic_id)
    extra_users = limit.extra_users if limit else None
    storage_mb = limit.storage_mb if limit else None
    return ClinicLimits(
        users=await _users(db, clinic_id),
        users_limit=None if extra_users is None else extra_users + 1,
        storage_bytes=await _storage_bytes(tenant, clinic_id),
        storage_limit_bytes=None if storage_mb is None else storage_mb * _MB,
    )


async def ensure_user_room(db: AsyncSession, clinic_id: UUID) -> None:
    """Refuse a new user in a clinic that has all its tier allows."""
    limit = await _tier_limit(db, clinic_id)
    if limit is None or limit.extra_users is None:
        return
    if await _users(db, clinic_id) >= limit.extra_users + 1:
        raise HTTPException(status.HTTP_403_FORBIDDEN, USER_LIMIT_REACHED)


async def require_storage_room(
    request: Request,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Dependency of every upload: refuse a file that does not fit in what
    the clinic's tier allows. The request's size stands for the file's —
    it is the file plus a few form fields."""
    limit = await _tier_limit(db, ctx.clinic_id)
    if limit is None or limit.storage_mb is None:
        return
    incoming = int(request.headers.get("content-length") or 0)
    if await _storage_bytes(tenant, ctx.clinic_id) + incoming > limit.storage_mb * _MB:
        raise HTTPException(status.HTTP_403_FORBIDDEN, STORAGE_LIMIT_REACHED)
