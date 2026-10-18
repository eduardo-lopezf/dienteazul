"""What the control plane reads from a deployment, and the one thing it
writes: a new clinic with its holder (ADR 0049 rules 4 and 6).

Mounted at ``/api/v1/ops``. Not for the clinic's users: no staff token
opens it. The caller is the operator's control plane, which signs a
short-lived token with ``CONTROL_PLANE_SECRET``.

The routes answer ``404`` — they do not exist — while that secret is
unset, and always under ``self`` custody: a self-hosted deployment
answers to nobody (ADR 0028).
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.config import settings
from app.core.auth.models import Clinic, ClinicMembership, TierLimit, User
from app.core.auth.schemas import _validate_iana_timezone
from app.core.auth.service import hash_password, validate_password_strength
from app.core.contracts import ReferenceSpecialties, provider
from app.core.events import event_bus
from app.core.events.types import EventType
from app.core.plugins.apps import (
    AppCatalogError,
    AppTier,
    load_app_catalog,
    mandatory_apps,
    read_app_catalog,
    required_apps,
)
from app.core.privacy.policy import CustodyMode
from app.core.privacy.tiers import (
    INDIVIDUAL_TIERS,
    AccountTier,
    TierCustodyError,
    validate_tier_custody,
)
from app.core.schemas import ApiResponse
from app.core.tenancy import TenantContext
from app.core.tenancy.dependencies import get_tenant
from app.core.tenancy.usage import BACKUPS_FOLDER
from app.database import get_db

from . import snapshot
from .purge import purge_clinic
from .usage import ClinicState, cached_measure, clinic_log, clinic_states

#: What a control-plane token must name as its audience, so a token
#: signed for anything else — a staff session, a budget link — is refused
#: even if the keys were ever the same.
OPS_AUDIENCE = "dienteazul-ops"

_bearer = HTTPBearer(auto_error=False)


async def require_control_plane(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> None:
    if not settings.CONTROL_PLANE_SECRET or tenant.privacy.custody_mode is CustodyMode.SELF:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if credentials is None:
        raise unauthorized
    try:
        jwt.decode(
            credentials.credentials,
            settings.CONTROL_PLANE_SECRET,
            algorithms=["HS256"],
            audience=OPS_AUDIENCE,
            options={"require": ["exp"]},
        )
    except PyJWTError:
        raise unauthorized from None


router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(require_control_plane)])


class ClinicUsageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime
    account_tier: str
    #: Its own limits, over its tier's; a key absent inherits.
    limits: dict[str, int | None]
    apps: list[str] | None
    users: int
    #: ``deactivated`` | ``active`` | ``offline`` | ``inactive``; read now,
    #: unlike the sizes, with the three dates it is worked out from.
    status: str
    last_access_at: datetime | None
    deactivated_at: datetime | None
    deletable_from: datetime | None
    #: ``accepted`` | ``outdated`` | ``declined`` | ``pending`` | ``not_asked``, and when.
    privacy: str
    privacy_at: datetime | None
    #: The version of the agreement accepted, where one was kept.
    privacy_version: str | None
    database_bytes: int
    database_rows: int
    storage_bytes: int
    storage_files: int


class DeploymentUsageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    database_bytes: int
    shared_database_bytes: int
    storage_bytes: int
    storage_files: int
    measured_at: datetime
    clinics: list[ClinicUsageResponse]


class LogEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    at: datetime
    kind: str
    user_id: UUID | None
    role: str | None
    area: str | None


@router.get("/usage", response_model=ApiResponse[DeploymentUsageResponse])
async def get_usage(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
    refresh: bool = False,
) -> ApiResponse[DeploymentUsageResponse]:
    """Database and file storage of the deployment, and of each clinic.

    Measured at most once every ten minutes; ``refresh=true`` measures
    again now. A clinic's database figure is its share of the tables it
    has rows in — see ``app.core.ops.usage``.
    """
    root = Path(settings.STORAGE_LOCAL_PATH) / tenant.storage_prefix
    usage = await cached_measure(db, root, refresh=refresh)
    states = await clinic_states(db)
    return ApiResponse(
        data=DeploymentUsageResponse(
            database_bytes=usage.database_bytes,
            shared_database_bytes=usage.shared_database_bytes,
            storage_bytes=usage.storage_bytes,
            storage_files=usage.storage_files,
            measured_at=usage.measured_at,
            clinics=[
                ClinicUsageResponse(**asdict(clinic), **asdict(states[clinic.id]))
                # One deleted since the sizes were measured has no state.
                for clinic in usage.clinics
                if clinic.id in states
            ],
        )
    )


@router.get("/clinics/{clinic_id}/log", response_model=ApiResponse[list[LogEntryResponse]])
async def get_clinic_log(
    clinic_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=500),
) -> ApiResponse[list[LogEntryResponse]]:
    """Sign-ins, sign-outs and newly created records of one clinic,
    newest first. Identifiers and table names only."""
    if await db.get(Clinic, clinic_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clinic not found")
    entries = await clinic_log(db, clinic_id, limit)
    return ApiResponse(data=[LogEntryResponse.model_validate(e) for e in entries])


#: Tiers sold to one professional rather than to a clinic: the clinic
#: record carries the holder's own name and tax id.
_INDIVIDUAL_TIERS = INDIVIDUAL_TIERS


class ClinicCreate(BaseModel):
    """A new clinic and the professional who holds it."""

    account_tier: AccountTier
    timezone: str = Field(max_length=64)
    #: RFC — the holder's under an individual tier, the clinic's otherwise.
    tax_id: str = Field(min_length=1, max_length=20)

    holder_first_name: str = Field(min_length=1, max_length=100)
    holder_last_name: str = Field(min_length=1, max_length=100)
    holder_email: EmailStr
    #: Cédula profesional.
    holder_professional_id: str = Field(min_length=1, max_length=50)
    #: The holder's first password, given by the control plane. Only its
    #: hash is kept, and the holder has to replace it at the first sign-in
    #: (``users.must_change_password``).
    holder_password: str = Field(min_length=8)

    # The clinic's own details. Required by every tier that is not an
    # individual one, ignored by those that are.
    #: Apps the clinic is set up with, by name. Must hold every App that
    #: is mandatory for the tier, and whatever the chosen ones require.
    apps: list[str]
    #: Apps it does not get but may switch on itself (Settings → Apps).
    available_apps: list[str] = []
    #: Disciplines the clinic's treatment catalogue starts with, by key.
    #: Left out, it gets the baseline ones, as after ``/auth/setup``.
    specialties: list[str] | None = None

    clinic_name: str | None = Field(default=None, min_length=1, max_length=200)
    clinic_legal_name: str | None = Field(default=None, max_length=200)
    clinic_phone: str | None = Field(default=None, max_length=20)
    clinic_email: EmailStr | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _validate_iana_timezone(value)

    @model_validator(mode="after")
    def clinic_tiers_name_the_clinic(self) -> ClinicCreate:
        if self.account_tier not in _INDIVIDUAL_TIERS and not self.clinic_name:
            raise ValueError(f"clinic_name is required for the '{self.account_tier}' tier")
        return self


class AppResponse(BaseModel):
    name: str
    tier: str
    #: Whether the deployment is running it. Decided at boot.
    enabled: bool
    #: What ``apps.json`` says now, when it differs from what is running:
    #: the edit takes effect at the next restart.
    pending_enabled: bool | None
    #: Other Apps it cannot run without.
    requires: list[str]
    #: Account tiers whose clinics always have it.
    mandatory_for: list[str]


@router.get("/apps", response_model=ApiResponse[list[AppResponse]])
async def list_apps() -> ApiResponse[list[AppResponse]]:
    """The deployment's Apps, **read from ``apps.json`` on every request**,
    and for which account tiers each is mandatory — what there is to
    choose from when creating a clinic.

    The file is the list; what is running is a fact about the process. An
    App the file has and the process does not run yet — it was added or
    switched on since boot — is listed as not enabled, with
    ``pending_enabled``.
    """
    try:
        on_disk = read_app_catalog()
    except (OSError, ValueError, KeyError, TypeError, AppCatalogError) as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"apps.json cannot be read: {exc}"
        ) from exc
    running = {app.name: app for app in load_app_catalog()}
    return ApiResponse(
        data=[
            AppResponse(
                name=app.name,
                tier=app.tier.value,
                enabled=app.name in running and running[app.name].enabled,
                pending_enabled=(
                    app.enabled
                    if app.name not in running or running[app.name].enabled != app.enabled
                    else None
                ),
                requires=required_apps(app),
                mandatory_for=[
                    tier.value
                    for tier in AccountTier
                    if app.tier is not AppTier.OPTIONAL or tier.value in app.core_for_tiers
                ],
            )
            for app in on_disk
        ]
    )


class SpecialtyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    names: dict[str, str]
    #: Every clinic has it.
    required: bool


@router.get("/specialties", response_model=ApiResponse[list[SpecialtyResponse]])
async def list_specialties() -> ApiResponse[list[SpecialtyResponse]]:
    """The disciplines a clinic's treatment catalogue can start with.
    None when the deployment does not run the Treatments App."""
    reference = provider(ReferenceSpecialties)
    return ApiResponse(
        data=[
            SpecialtyResponse.model_validate(s)
            for s in (reference.available() if reference else [])
        ]
    )


def _chosen_specialties(chosen: list[str] | None) -> list[str] | None:
    """``chosen``, once it is a set of disciplines a clinic can start with."""
    if chosen is None:
        return None
    reference = provider(ReferenceSpecialties)
    known = {s.key: s for s in (reference.available() if reference else [])}
    if unknown := [key for key in chosen if key not in known]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"not a specialty: {', '.join(unknown)}"
        )
    if missing := [key for key, s in known.items() if s.required and key not in chosen]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"every clinic has the specialty: {', '.join(missing)}",
        )
    return [key for key in known if key in chosen]


def _announce_tier(db: AsyncSession, clinic: Clinic, tier: str) -> None:
    """Say so after the commit when ``clinic`` moves to another tier.

    Modules keep what a tier implies on their side: ``professionals`` gives
    the holder of an individual practice their profile.
    """
    if clinic.account_tier == tier:
        return
    event_bus.publish_after_commit(
        db,
        EventType.CLINIC_ACCOUNT_TIER_CHANGED,
        {"clinic_id": str(clinic.id), "account_tier": tier, "previous_tier": clinic.account_tier},
    )


def _chosen_apps(chosen: list[str], tier: AccountTier) -> list[str]:
    """``chosen`` in catalog order, once it is a set a clinic can have."""
    catalog = {app.name: app for app in load_app_catalog()}
    refusal: str | None = None
    if unavailable := [name for name in chosen if name not in catalog or not catalog[name].enabled]:
        refusal = f"not an App of this deployment: {', '.join(unavailable)}"
    elif missing := [name for name in mandatory_apps(tier.value) if name not in chosen]:
        refusal = f"mandatory for the '{tier.value}' tier: {', '.join(missing)}"
    else:
        for name in chosen:
            if needs := [other for other in required_apps(catalog[name]) if other not in chosen]:
                refusal = f"'{name}' cannot run without: {', '.join(needs)}"
                break
    if refusal:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, refusal)
    return [name for name in catalog if name in chosen]


def _offered_apps(offered: list[str], chosen: list[str]) -> list[str]:
    """``offered`` in catalog order: Apps of the deployment the clinic was
    not given and may switch on itself."""
    catalog = {app.name: app for app in load_app_catalog()}
    if unavailable := [n for n in offered if n not in catalog or not catalog[n].enabled]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"not an App of this deployment: {', '.join(unavailable)}",
        )
    return [name for name in catalog if name in offered and name not in chosen]


class ClinicCreatedResponse(BaseModel):
    clinic_id: UUID
    name: str
    holder_user_id: UUID
    #: The e-mail already had an account that belonged to no clinic: it
    #: was made holder of this one as it is, password included.
    holder_existed: bool


@router.post(
    "/clinics",
    response_model=ApiResponse[ClinicCreatedResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_clinic(
    data: ClinicCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> ApiResponse[ClinicCreatedResponse]:
    """Create a clinic and its holder, who becomes its administrator.

    What ``/auth/setup`` does for the first clinic of a deployment, for
    every one after it. Under an individual tier the clinic record is the
    holder's practice: it takes the holder's name.

    One e-mail, one account, one clinic. An e-mail whose account already
    belongs to a clinic is refused: that person needs another e-mail for
    a new account, or to be removed from the clinic first. An account
    that belongs to none — it was removed — becomes the holder as it is,
    password included.
    """
    try:
        validate_tier_custody(data.account_tier, tenant.privacy.custody_mode)
    except TierCustodyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    is_valid, error = validate_password_strength(data.holder_password)
    if not is_valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, error)
    apps = _chosen_apps(data.apps, data.account_tier)
    available_apps = _offered_apps(data.available_apps, apps)
    specialties = _chosen_specialties(data.specialties)

    holder = await db.scalar(select(User).where(User.email == data.holder_email))
    holder_existed = holder is not None
    if holder is not None:
        if not holder.is_active:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "The account with this e-mail is deactivated"
            )
        belongs_to = list(
            await db.scalars(
                select(Clinic.name)
                .join(ClinicMembership, ClinicMembership.clinic_id == Clinic.id)
                .where(ClinicMembership.user_id == holder.id)
            )
        )
        if belongs_to:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"This e-mail already belongs to a user of: {', '.join(belongs_to)}",
            )

    individual = data.account_tier in _INDIVIDUAL_TIERS
    clinic = Clinic(
        name=(
            f"{data.holder_first_name} {data.holder_last_name}" if individual else data.clinic_name
        ),
        tax_id=data.tax_id,
        legal_name=None if individual else data.clinic_legal_name,
        phone=None if individual else data.clinic_phone,
        email=None if individual else data.clinic_email,
        account_tier=data.account_tier.value,
        apps=apps,
        available_apps=available_apps,
        timezone=data.timezone,
        # Its holder is taken through the welcome at the first sign-in.
        onboarding_pending=True,
    )
    if holder is None:
        holder = User(
            email=data.holder_email,
            password_hash=hash_password(data.holder_password),
            first_name=data.holder_first_name,
            last_name=data.holder_last_name,
            professional_id=data.holder_professional_id,
            must_change_password=True,
        )
        db.add(holder)
    elif not holder.professional_id:
        # The one thing filled in on an existing account, and only if empty.
        holder.professional_id = data.holder_professional_id
    db.add(clinic)
    await db.flush()
    db.add(ClinicMembership(user_id=holder.id, clinic_id=clinic.id, role="admin"))

    # Modules install their baseline data on this event — the catalog its
    # VAT types, categories and specialties — exactly as after /auth/setup.
    created = {"clinic_id": str(clinic.id), "created_by": str(holder.id), "name": clinic.name}
    if specialties is not None:
        created["specialties"] = specialties
    event_bus.publish_after_commit(db, EventType.CLINIC_CREATED, created)
    return ApiResponse(
        data=ClinicCreatedResponse(
            clinic_id=clinic.id,
            name=clinic.name,
            holder_user_id=holder.id,
            holder_existed=holder_existed,
        )
    )


class ClinicStateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    last_access_at: datetime | None
    deactivated_at: datetime | None
    deletable_from: datetime | None
    #: ``accepted`` | ``outdated`` | ``declined`` | ``pending`` | ``not_asked``, and when.
    privacy: str
    privacy_at: datetime | None
    #: The version of the agreement accepted, where one was kept.
    privacy_version: str | None


async def _set_deactivated(db: AsyncSession, clinic_id: UUID, deactivated: bool) -> ClinicState:
    clinic = await db.get(Clinic, clinic_id)
    if clinic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clinic not found")
    if deactivated and clinic.deactivated_at is None:
        # Kept if already set: the wait before deletion counts from the
        # first time, not from the last click.
        clinic.deactivated_at = datetime.now(UTC)
    elif not deactivated:
        clinic.deactivated_at = None
        # Opened again, a holder who declined the privacy agreement is
        # back to being asked: pending, not declined.
        clinic.privacy_declined_at = None
    await db.flush()
    return (await clinic_states(db))[clinic_id]


@router.post("/clinics/{clinic_id}/deactivate", response_model=ApiResponse[ClinicStateResponse])
async def deactivate_clinic(
    clinic_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> ApiResponse[ClinicStateResponse]:
    """Close a clinic to its members. Nothing of it is deleted, and
    reactivating brings everything back."""
    state = await _set_deactivated(db, clinic_id, True)
    return ApiResponse(data=ClinicStateResponse.model_validate(state))


@router.post("/clinics/{clinic_id}/reactivate", response_model=ApiResponse[ClinicStateResponse])
async def reactivate_clinic(
    clinic_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> ApiResponse[ClinicStateResponse]:
    """Open a deactivated clinic again."""
    state = await _set_deactivated(db, clinic_id, False)
    return ApiResponse(data=ClinicStateResponse.model_validate(state))


class OpsUserResponse(BaseModel):
    """A staff account, as the operator's console manages it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    first_name: str
    last_name: str
    professional_id: str | None
    is_active: bool
    must_change_password: bool
    #: Their role in the clinic asked about; absent when read on their own.
    role: str | None = None


class OpsUserUpdate(BaseModel):
    """The profile fields an operator may correct. Left out, a field stays."""

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    professional_id: str | None = Field(default=None, max_length=50)


@router.get("/clinics/{clinic_id}/users", response_model=ApiResponse[list[OpsUserResponse]])
async def list_clinic_users(
    clinic_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> ApiResponse[list[OpsUserResponse]]:
    """The staff accounts of one clinic, with their role in it."""
    if await db.get(Clinic, clinic_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clinic not found")
    rows = await db.execute(
        select(User, ClinicMembership.role)
        .join(ClinicMembership, ClinicMembership.user_id == User.id)
        .where(ClinicMembership.clinic_id == clinic_id)
        .order_by(ClinicMembership.created_at)
    )
    return ApiResponse(
        data=[
            OpsUserResponse.model_validate(user).model_copy(update={"role": role})
            for user, role in rows
        ]
    )


@router.patch("/users/{user_id}", response_model=ApiResponse[OpsUserResponse])
async def update_user(
    user_id: UUID, data: OpsUserUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> ApiResponse[OpsUserResponse]:
    """Correct a staff account's profile: name, e-mail, professional id.
    Never its password."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    changes = data.model_dump(exclude_unset=True)
    if "email" in changes and changes["email"] != user.email:
        taken = await db.scalar(select(User.id).where(User.email == changes["email"]))
        if taken:
            raise HTTPException(status.HTTP_409_CONFLICT, "A user with this e-mail already exists")
    for field, value in changes.items():
        # A name or an e-mail cannot be emptied; the professional id can.
        if value is None and field != "professional_id":
            continue
        setattr(user, field, value)
    await db.flush()
    return ApiResponse(data=OpsUserResponse.model_validate(user))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> None:
    """Delete a staff account for good. **Not in production.**

    A convenience for development, where test accounts pile up. In
    production an account is deactivated, never deleted: what it wrote —
    notes, appointments, signatures — has to keep its author. That is
    also why an account something still points at is refused here too.
    """
    if settings.ENVIRONMENT == "production":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Accounts are not deleted in production")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    try:
        async with db.begin_nested():
            await db.delete(user)
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Records still point at this account; deactivate it instead"
        ) from None


class ClinicDetailResponse(BaseModel):
    """Everything a clinic was created with, as it stands now."""

    id: UUID
    name: str
    account_tier: str
    timezone: str
    tax_id: str
    legal_name: str | None
    phone: str | None
    email: str | None
    apps: list[str] | None
    #: Apps it may switch on itself.
    available_apps: list[str]
    #: Its own limits, over its tier's; a key absent inherits.
    limits: dict[str, int | None]
    #: The disciplines switched on in its treatment catalogue.
    specialties: list[str]
    #: Its longest-standing administrator.
    holder: OpsUserResponse | None


class ClinicUpdate(BaseModel):
    """What creation asks about the clinic, to be changed afterwards. The
    holder's own details are changed on their account
    (``PATCH /ops/users/{id}``)."""

    account_tier: AccountTier
    timezone: str = Field(max_length=64)
    tax_id: str = Field(min_length=1, max_length=20)
    apps: list[str]
    available_apps: list[str] = []
    specialties: list[str] | None = None
    clinic_name: str | None = Field(default=None, min_length=1, max_length=200)
    clinic_legal_name: str | None = Field(default=None, max_length=200)
    clinic_phone: str | None = Field(default=None, max_length=20)
    clinic_email: EmailStr | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _validate_iana_timezone(value)

    @model_validator(mode="after")
    def clinic_tiers_name_the_clinic(self) -> ClinicUpdate:
        if self.account_tier not in _INDIVIDUAL_TIERS and not self.clinic_name:
            raise ValueError(f"clinic_name is required for the '{self.account_tier}' tier")
        return self


async def _holder(db: AsyncSession, clinic_id: UUID) -> User | None:
    return await db.scalar(
        select(User)
        .join(ClinicMembership, ClinicMembership.user_id == User.id)
        .where(ClinicMembership.clinic_id == clinic_id, ClinicMembership.role == "admin")
        .order_by(ClinicMembership.created_at)
        .limit(1)
    )


async def _detail(
    db: AsyncSession, clinic: Clinic, specialties: list[str] | None = None
) -> ClinicDetailResponse:
    if specialties is None:
        reference = provider(ReferenceSpecialties)
        specialties = await reference.enabled(db, clinic.id) if reference else []
    holder = await _holder(db, clinic.id)
    return ClinicDetailResponse(
        id=clinic.id,
        name=clinic.name,
        account_tier=clinic.account_tier,
        timezone=clinic.timezone,
        tax_id=clinic.tax_id,
        legal_name=clinic.legal_name,
        phone=clinic.phone,
        email=clinic.email,
        apps=clinic.apps,
        available_apps=clinic.available_apps or [],
        limits=clinic.limits or {},
        specialties=specialties,
        holder=(
            OpsUserResponse.model_validate(holder).model_copy(update={"role": "admin"})
            if holder
            else None
        ),
    )


async def _clinic(clinic_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> Clinic:
    clinic = await db.get(Clinic, clinic_id)
    if clinic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clinic not found")
    return clinic


@router.get("/clinics/{clinic_id}", response_model=ApiResponse[ClinicDetailResponse])
async def get_clinic(
    clinic: Annotated[Clinic, Depends(_clinic)], db: Annotated[AsyncSession, Depends(get_db)]
) -> ApiResponse[ClinicDetailResponse]:
    """A clinic with everything it was created with: tier, time zone, tax
    id, its own details, Apps, specialties and holder."""
    return ApiResponse(data=await _detail(db, clinic))


@router.patch("/clinics/{clinic_id}", response_model=ApiResponse[ClinicDetailResponse])
async def update_clinic(
    data: ClinicUpdate,
    clinic: Annotated[Clinic, Depends(_clinic)],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> ApiResponse[ClinicDetailResponse]:
    """Change what a clinic was created with, under the rules of creation:
    the Apps mandatory for the tier, what each App requires, the specialty
    every clinic has. Under an individual tier the clinic record is the
    holder's practice and takes the holder's name."""
    try:
        validate_tier_custody(data.account_tier, tenant.privacy.custody_mode)
    except TierCustodyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    apps = _chosen_apps(data.apps, data.account_tier)
    specialties = _chosen_specialties(data.specialties)

    clinic.available_apps = _offered_apps(data.available_apps, apps)
    _announce_tier(db, clinic, data.account_tier.value)
    clinic.account_tier = data.account_tier.value
    clinic.timezone = data.timezone
    clinic.tax_id = data.tax_id
    clinic.apps = apps
    if data.account_tier in _INDIVIDUAL_TIERS:
        holder = await _holder(db, clinic.id)
        if holder:
            clinic.name = f"{holder.first_name} {holder.last_name}"
    else:
        clinic.name = data.clinic_name
        clinic.legal_name = data.clinic_legal_name
        clinic.phone = data.clinic_phone
        clinic.email = data.clinic_email
    await db.flush()

    if specialties is not None:
        event_bus.publish_after_commit(
            db,
            EventType.CLINIC_SPECIALTIES_SET,
            {"clinic_id": str(clinic.id), "specialties": specialties},
        )
    # The packs change after the commit; answer with what was asked for.
    return ApiResponse(data=await _detail(db, clinic, specialties))


class TierLimits(BaseModel):
    """What a clinic of a tier is allowed; ``None`` is no limit."""

    model_config = ConfigDict(from_attributes=True)

    #: Users it may add besides its holder.
    extra_users: int | None = Field(default=None, ge=0)
    #: Disk space for its files, in megabytes.
    storage_mb: int | None = Field(default=None, gt=0)


@router.put("/clinics/{clinic_id}/limits", response_model=ApiResponse[ClinicDetailResponse])
async def set_clinic_limits(
    data: TierLimits,
    clinic: Annotated[Clinic, Depends(_clinic)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ClinicDetailResponse]:
    """Set a clinic's own limits, over its tier's. A field sent overrides
    that limit — ``null`` being "no limit" for this clinic — and a field
    left out goes back to the tier's. ``{}`` inherits both."""
    clinic.limits = data.model_dump(exclude_unset=True) or None
    await db.flush()
    return ApiResponse(data=await _detail(db, clinic))


class ClinicTierUpdate(BaseModel):
    account_tier: AccountTier


@router.put("/clinics/{clinic_id}/tier", response_model=ApiResponse[ClinicDetailResponse])
async def set_clinic_tier(
    data: ClinicTierUpdate,
    clinic: Annotated[Clinic, Depends(_clinic)],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> ApiResponse[ClinicDetailResponse]:
    """Move a clinic to another account tier, and nothing else.

    It keeps its Apps and gains the ones the new tier makes mandatory,
    with what they require. Under an individual tier the record takes its
    holder's name; moved to a clinic tier it keeps the name it has until
    somebody gives it its own. The new tier's limits hold from the next
    request on; a clinic already over them keeps what it has.
    """
    try:
        validate_tier_custody(data.account_tier, tenant.privacy.custody_mode)
    except TierCustodyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    _announce_tier(db, clinic, data.account_tier.value)
    clinic.account_tier = data.account_tier.value
    if clinic.apps is not None:
        catalog = {app.name: app for app in load_app_catalog()}
        apps = set(clinic.apps) | set(mandatory_apps(data.account_tier.value))
        while needed := {n for name in apps for n in required_apps(catalog[name])} - apps:
            apps |= needed
        clinic.apps = [name for name in catalog if name in apps]
        clinic.available_apps = [n for n in clinic.available_apps or [] if n not in apps]
    if data.account_tier in _INDIVIDUAL_TIERS:
        holder = await _holder(db, clinic.id)
        if holder:
            clinic.name = f"{holder.first_name} {holder.last_name}"
    await db.flush()
    return ApiResponse(data=await _detail(db, clinic))


@router.delete("/clinics/{clinic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_clinic(
    clinic: Annotated[Clinic, Depends(_clinic)],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> None:
    """Delete a clinic for good, with every row and file of its own and
    the accounts that belonged to no other. **Not in production.**

    For the clinics made to try something out in development. A real
    clinic is deactivated: it holds records the law makes it keep.
    """
    if settings.ENVIRONMENT == "production":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Clinics are not deleted in production")
    root = Path(settings.STORAGE_LOCAL_PATH) / tenant.storage_prefix
    try:
        async with db.begin_nested():
            await purge_clinic(db, clinic.id, root)
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Could not delete every record of the clinic: {exc.orig}"
        ) from None


@router.get("/limits", response_model=ApiResponse[dict[AccountTier, TierLimits]])
async def get_limits(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict[AccountTier, TierLimits]]:
    """What each account tier is allowed. A tier left out has no limit."""
    rows = await db.scalars(select(TierLimit))
    return ApiResponse(data={AccountTier(row.tier): TierLimits.model_validate(row) for row in rows})


@router.put("/limits", response_model=ApiResponse[dict[AccountTier, TierLimits]])
async def set_limits(
    data: dict[AccountTier, TierLimits],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict[AccountTier, TierLimits]]:
    """Replace what every account tier is allowed; a tier left out has no
    limit. Held from the next request on: a clinic already over a limit
    keeps what it has and is refused more."""
    await db.execute(delete(TierLimit))
    db.add_all(TierLimit(tier=tier.value, **limits.model_dump()) for tier, limits in data.items())
    await db.flush()
    return ApiResponse(data=data)


class ClinicAppsUpdate(BaseModel):
    """A clinic's Apps, on their own: the ones it has and the ones it may
    switch on itself. An App on neither list is not available to it."""

    apps: list[str]
    available_apps: list[str] = []


@router.put("/clinics/{clinic_id}/apps", response_model=ApiResponse[ClinicDetailResponse])
async def set_clinic_apps(
    data: ClinicAppsUpdate,
    clinic: Annotated[Clinic, Depends(_clinic)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ClinicDetailResponse]:
    """Give a clinic an App, offer it one, or take one away — without
    touching anything else about it. The rules of creation hold: what its
    tier makes mandatory stays, and an App comes with what it requires.
    Takes effect at the clinic's next request."""
    try:
        tier = AccountTier(clinic.account_tier)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    clinic.apps = _chosen_apps(data.apps, tier)
    clinic.available_apps = _offered_apps(data.available_apps, clinic.apps)
    await db.flush()
    return ApiResponse(data=await _detail(db, clinic))


# --- A whole copy of the deployment -----------------------------------------


def _copy_allowed(tenant: TenantContext) -> None:
    # A copy carries every record. Under ``byok`` the operator holds no key
    # to the clinics' data, so it does not leave through the operator.
    if tenant.privacy.custody_mode is not CustodyMode.MANAGED:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Whole copies are taken only under managed custody"
        )


async def _revisions(db: AsyncSession) -> list[str]:
    # A schema made without Alembic (the test suite's) has no revisions.
    if await db.scalar(text("SELECT to_regclass('alembic_version')")) is None:
        return []
    rows = await db.execute(text("SELECT version_num FROM alembic_version ORDER BY 1"))
    return list(rows.scalars())


def _manifest(revisions: list[str]) -> dict:
    return {
        "format": snapshot.FORMAT,
        "environment": settings.ENVIRONMENT,
        "taken_at": datetime.now(UTC).isoformat(),
        "revisions": revisions,
    }


def _dsn(db: AsyncSession) -> str:
    # The database this very session is bound to — never the one the
    # settings name, which a test run does not use.
    return snapshot.libpq_dsn(db.get_bind().url.render_as_string(hide_password=False))


@router.get("/snapshot")
async def export_snapshot(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> FileResponse:
    """The whole deployment as one ``tar.gz``: its database and its files.
    **Every record of every clinic leaves in it** (ADR 0049 rule 4,
    amended) — it is how the control plane copies one environment into
    another."""
    _copy_allowed(tenant)
    manifest = _manifest(await _revisions(db))
    root = Path(settings.STORAGE_LOCAL_PATH) / tenant.storage_prefix
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as handle:
        path = Path(handle.name)
    await asyncio.to_thread(snapshot.build, _dsn(db), root, path, manifest)
    return FileResponse(
        path,
        media_type="application/gzip",
        filename=f"dienteazul-{settings.ENVIRONMENT}.tar.gz",
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


class SnapshotRestoredResponse(BaseModel):
    #: The copy of what this deployment held before, in its backups folder.
    backup: str
    clinics: int
    files: int
    #: Where the copy came from and when it was taken.
    source: str
    taken_at: str


@router.put("/snapshot", response_model=ApiResponse[SnapshotRestoredResponse])
async def import_snapshot(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
    confirm: str = Query(default=""),
) -> ApiResponse[SnapshotRestoredResponse]:
    """**Replace this whole deployment** with a copy another one exported:
    every clinic, account, record and file it holds is gone afterwards.

    ``confirm=replace`` is required. A copy of what it held is kept first
    in its backups folder; the database is then replaced in one
    transaction, and only then the files. A copy taken at other schema
    revisions is refused (``409``): both sides must run the same version.
    """
    _copy_allowed(tenant)
    if confirm != "replace":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Replacing the deployment needs confirm=replace"
        )
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as handle:
        upload = Path(handle.name)
        async for chunk in request.stream():
            handle.write(chunk)
    try:
        try:
            manifest = await asyncio.to_thread(snapshot.read_manifest, upload)
            revisions = await _revisions(db)
            snapshot.check_versions(manifest, revisions)
        except snapshot.SnapshotRefusedError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        # Nothing of this request may hold the schema the restore empties.
        await db.commit()

        dsn = _dsn(db)
        root = Path(settings.STORAGE_LOCAL_PATH) / tenant.storage_prefix
        backups = root / BACKUPS_FOLDER
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / f"before-copy-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.tar.gz"
        await asyncio.to_thread(snapshot.build, dsn, root, backup, _manifest(revisions))
        files = await asyncio.to_thread(snapshot.restore, dsn, root, upload)
    finally:
        upload.unlink(missing_ok=True)

    clinics = await db.scalar(select(func.count()).select_from(Clinic))
    return ApiResponse(
        data=SnapshotRestoredResponse(
            backup=backup.name,
            clinics=clinics,
            files=files,
            source=str(manifest.get("environment", "")),
            taken_at=str(manifest.get("taken_at", "")),
        )
    )
