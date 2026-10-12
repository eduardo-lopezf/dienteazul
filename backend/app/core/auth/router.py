"""Authentication router with rate limiting."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from fastapi.security import OAuth2PasswordRequestForm
from jwt import PyJWTError
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.events import event_bus
from app.core.events.types import EventType
from app.core.plugins import module_registry
from app.core.plugins.apps import modules_outside
from app.core.privacy import TierCustodyError, tiers_available_under, validate_tier_custody
from app.core.schemas import ApiResponse, PaginatedApiResponse
from app.core.tenancy import TenantContext, get_tenant
from app.database import get_db

from . import sessions
from .dependencies import (
    ClinicContext,
    declares_permissions,
    get_clinic_context,
    get_current_user,
    require_permission,
)
from .models import Clinic, ClinicBrandLogo, ClinicLetterhead, ClinicMembership, User
from .permissions import (
    CORE_PERMISSIONS,
    ROLES,
    expand_permissions,
    get_role_permissions,
    has_permission,
)
from .schemas import (
    AuthResponse,
    ClinicMetadataResponse,
    ClinicMetadataUpdate,
    ClinicResponse,
    MeResponse,
    PasswordChange,
    ProfessionalResponse,
    SetupStatusResponse,
    SystemSetup,
    TokenRefresh,
    TokenResponse,
    UserAccessUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
    UserWithRoleResponse,
)
from .service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_password_strength,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
# Rate limiting guards production. Dev + test disable it so local flows
# (manual clicking, Playwright E2E, pytest) don't run into 5/minute
# caps after a handful of reloads.
_limiter_enabled = settings.ENVIRONMENT == "production" and not settings.TESTING


def build_limiter(storage_uri: str, *, enabled: bool) -> Limiter:
    """The limiter, counting in ``storage_uri`` or, when empty, in memory.

    Memory is per process: two backends each allow the full limit. A
    shared store makes it one limit, and losing that store must not take
    the login down with it — so with one configured, the limiter falls
    back to memory while it is unreachable and returns to it afterwards.
    """
    if not storage_uri:
        return Limiter(key_func=get_remote_address, enabled=enabled)
    return Limiter(
        key_func=get_remote_address,
        enabled=enabled,
        storage_uri=storage_uri,
        in_memory_fallback_enabled=True,
    )


limiter = build_limiter(settings.RATE_LIMIT_STORAGE_URI, enabled=_limiter_enabled)

logger = logging.getLogger(__name__)


async def _refresh_rate_key(request: Request) -> str:
    """Key the refresh limiter by user, not IP.

    A shared edge proxy (Cloudflare → Nuxt SSR → backend) collapses every
    real client to the same socket peer, so an IP-keyed limiter caps the
    whole tenant after a handful of refreshes. Decoding the refresh token
    here gives a per-user bucket; we fall back to the proxy-aware client
    IP if the body is missing or unreadable.
    """
    try:
        body = await request.json()
        token = body.get("refresh_token") if isinstance(body, dict) else None
        if token:
            payload = decode_token(token)
            sub = payload.get("sub")
            if sub:
                return f"refresh:{sub}"
    except Exception:
        pass
    return get_remote_address(request)


@router.get("/setup/status", response_model=ApiResponse[SetupStatusResponse])
async def setup_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> ApiResponse[SetupStatusResponse]:
    """Whether the system already has an account (drives the first-run wizard).

    Also reports the deployment's custody mode and the tiers it may
    create, so the wizard offers a choice that will be accepted rather
    than one the POST refuses.
    """
    count = await db.scalar(select(func.count()).select_from(User))
    mode = tenant.privacy.custody_mode
    return ApiResponse(
        data=SetupStatusResponse(
            initialized=bool(count),
            custody_mode=mode.value,
            available_account_tiers=[tier.value for tier in tiers_available_under(mode)],
        )
    )


@router.post("/setup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour")
async def setup(
    request: Request,
    data: SystemSetup,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> TokenResponse:
    """First-run: create the first admin account and its clinic, then log them in.

    Self-closing: once any user exists the system is initialized and this
    endpoint returns 409.
    """
    # ponytail: guard por count==0; una carrera entre dos setups simultáneos es
    # despreciable en un arranque de operador único. Subir a constraint/lock solo
    # si esto se vuelve multi-tenant self-serve.
    existing = await db.scalar(select(func.count()).select_from(User))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System already initialized",
        )

    is_valid, error_msg = validate_password_strength(data.admin_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_msg,
        )

    # Both halves of the commercial pairing are mandatory and neither is
    # defaulted: the tier arrives in the payload, the custody mode comes
    # from the deployment that is running (ADR 0024 keeps it out of this
    # database). This is one of the two places both are known at once, so
    # it is one of the two places the pair can be checked.
    try:
        validate_tier_custody(data.account_tier, tenant.privacy.custody_mode)
    except TierCustodyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    clinic = Clinic(
        name=data.clinic_name,
        tax_id=data.clinic_tax_id,
        account_tier=data.account_tier.value,
        timezone=data.timezone or "America/Mexico_City",
        currency=data.currency or "MXN",
    )
    db.add(clinic)
    await db.flush()

    user = User(
        email=data.admin_email,
        password_hash=hash_password(data.admin_password),
        first_name=data.admin_first_name,
        last_name=data.admin_last_name,
    )
    db.add(user)
    await db.flush()

    db.add(ClinicMembership(user_id=user.id, clinic_id=clinic.id, role="admin"))
    await db.commit()

    # Published after the commit so subscribers opening their own session
    # can see the clinic. Modules install their own baseline data here —
    # `catalog` seeds VAT types, categories, items and specialties — which
    # keeps core from importing a module (ADR 0003). The bus awaits its
    # handlers, so the catalog is ready before these tokens are returned;
    # it also swallows handler errors, so a seeding failure logs loudly
    # but never costs the admin their account.
    await event_bus.publish(
        EventType.CLINIC_CREATED,
        {"clinic_id": str(clinic.id), "created_by": str(user.id), "name": clinic.name},
    )

    session = await sessions.start_session(db, user.id)
    await db.commit()

    access_token = create_access_token(
        user.id,
        clinic_id=clinic.id,
        token_version=user.token_version,
        family_id=session.family_id,
    )
    refresh_token = create_refresh_token(
        user.id,
        token_version=user.token_version,
        jti=session.id,
        expires_at=session.expires_at,
    )

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Login and get access tokens."""
    # Find user by email
    result = await db.execute(
        select(User).options(selectinload(User.memberships)).where(User.email == form_data.username)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # No clinic, no sign-in.
    #
    # This used to let the account in with ``clinic_id = None``, able to do
    # nothing — every endpoint resolves a clinic — but holding a working
    # password that no screen showed: ``GET /users`` lists by membership,
    # so an account without one was invisible.
    #
    # Accounts reach that state through the product, not by accident:
    # ``DELETE /auth/users/{id}`` removes the membership and keeps the
    # account, so "remove from the clinic" left a login behind. This is
    # what makes that removal mean what it says.
    if not user.memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not assigned to a clinic",
        )

    clinic_id = user.memberships[0].clinic_id

    # Generate tokens. The session row is what makes this login endable
    # later — by logout, or by reuse detection killing its family.
    session = await sessions.start_session(db, user.id)
    await db.commit()

    access_token = create_access_token(
        user.id,
        clinic_id=clinic_id,
        token_version=user.token_version,
        family_id=session.family_id,
    )
    refresh_token = create_refresh_token(
        user.id,
        token_version=user.token_version,
        jti=session.id,
        expires_at=session.expires_at,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=AuthResponse)
@limiter.limit("10/minute", key_func=_refresh_rate_key)
async def refresh_token(
    request: Request,
    data: TokenRefresh,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthResponse:
    """Refresh access token using refresh token."""
    try:
        payload = decode_token(data.refresh_token)
        user_id = payload.get("sub")
        token_type = payload.get("type")
        token_version = payload.get("token_version", 0)
        raw_jti = payload.get("jti")

        # A refresh without a jti predates the session table and names no
        # row, so nothing could ever revoke it. Rejecting it logs those
        # holders out once, which is the point of the change.
        if user_id is None or token_type != "refresh" or raw_jti is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Fetch user with memberships and clinics
    result = await db.execute(
        select(User).options(selectinload(User.memberships)).where(User.id == UUID(user_id))
    )
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Check token version for revocation
    if user.token_version != token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    # Fetch memberships with clinics for response
    memberships_result = await db.execute(
        select(ClinicMembership)
        .options(selectinload(ClinicMembership.clinic))
        .where(ClinicMembership.user_id == user.id)
        .order_by(ClinicMembership.created_at)
    )
    memberships = memberships_result.scalars().all()

    clinics = [
        ClinicResponse(
            id=m.clinic.id,
            name=m.clinic.name,
            role=m.role,
            timezone=m.clinic.timezone,
            onboarding_pending=m.clinic.onboarding_pending,
            privacy_renewal=needs_renewal(m.clinic),
            deactivated=m.clinic.deactivated_at is not None,
        )
        for m in memberships
    ]

    # Get first clinic ID for token
    clinic_id = None
    if memberships:
        clinic_id = memberships[0].clinic_id

    # Spend the presented token and open its successor. A token seen
    # twice means two holders and no way to tell which is the thief, so
    # `rotate` revokes the whole family before raising.
    try:
        successor = await sessions.rotate(db, UUID(raw_jti))
    except sessions.RefreshReuseError:
        await db.commit()
        logger.warning("Refresh token reuse for user %s — session family revoked", user.id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        ) from None
    except sessions.InactiveFamilyError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session family has expired or is inactive",
        ) from None
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from None

    await db.commit()

    # Generate new tokens
    access_token = create_access_token(
        user.id,
        clinic_id=clinic_id,
        token_version=user.token_version,
        family_id=successor.family_id,
    )
    new_refresh_token = create_refresh_token(
        user.id,
        token_version=user.token_version,
        jti=successor.id,
        expires_at=successor.expires_at,
    )

    return AuthResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        user=UserResponse.model_validate(user),
        clinics=clinics,
    )


@router.post("/activity", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def record_activity(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Extend the idle timeout for the authenticated session family."""
    family_id = getattr(request.state, "auth_family_id", None)
    if family_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A session-bound access token is required",
        )
    if not await sessions.record_activity(db, family_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session family has expired or is inactive",
        )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def logout(
    request: Request,
    data: TokenRefresh,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """End the session the refresh token belongs to.

    Until now logging out cleared a cookie in the browser and left the
    tokens valid on the server for their full lifetime — seven days for
    the refresh. This revokes the whole family, so every token descended
    from that login stops working.

    Deliberately answers 204 whether or not the token was real, and takes
    no access token: an endpoint that reports which tokens exist is an
    oracle, and refusing to log somebody out because their token had
    already expired would be a refusal with no upside. The access token
    it was paired with still works until it expires — that is what
    ``token_version`` is for, and 15 minutes is the window this design
    accepts.
    """
    try:
        payload = decode_token(data.refresh_token)
    except PyJWTError:
        return

    raw_jti = payload.get("jti")
    if payload.get("type") != "refresh" or raw_jti is None:
        return

    try:
        await sessions.end_session(db, UUID(raw_jti))
    except ValueError:
        return
    await db.commit()


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    data: PasswordChange,
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Replace the caller's own password.

    The one thing an account with ``must_change_password`` may do besides
    reading its profile, and what clears that flag. The new password has
    to differ from the current one — otherwise an account handed a known
    password could "change" it to the same thing.
    """
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        )
    if data.new_password == data.current_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The new password must differ from the current one",
        )
    is_valid, error_msg = validate_password_strength(data.new_password)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error_msg)

    current_user.password_hash = hash_password(data.new_password)
    current_user.must_change_password = False


@router.get("/me", response_model=ApiResponse[MeResponse])
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[MeResponse]:
    """Get current user info, clinics, and permissions."""
    # Fetch memberships with clinics
    result = await db.execute(
        select(ClinicMembership)
        .options(selectinload(ClinicMembership.clinic))
        .where(ClinicMembership.user_id == current_user.id)
        .order_by(ClinicMembership.created_at)
    )
    memberships = result.scalars().all()

    clinics = [
        ClinicResponse(
            id=m.clinic.id,
            name=m.clinic.name,
            role=m.role,
            timezone=m.clinic.timezone,
            onboarding_pending=m.clinic.onboarding_pending,
            privacy_renewal=needs_renewal(m.clinic),
            deactivated=m.clinic.deactivated_at is not None,
        )
        for m in memberships
    ]

    # Compute effective permissions (use first clinic's role for MVP)
    permissions: list[str] = []
    if memberships:
        role = memberships[0].role
        role_perms = get_role_permissions(role)
        # Combine module permissions with core permissions
        all_perms = module_registry.get_all_permissions() + CORE_PERMISSIONS
        permissions = expand_permissions(role_perms, all_perms)
        # Not those of Apps the clinic does not have: the app hides by
        # permission, and a button for a route that answers 404 helps nobody.
        outside = modules_outside(memberships[0].clinic.apps)
        permissions = [p for p in permissions if p.split(".", 1)[0] not in outside]

    return ApiResponse(
        data=MeResponse(
            user=UserResponse.model_validate(current_user),
            clinics=clinics,
            permissions=permissions,
        )
    )


@router.get("/users", response_model=PaginatedApiResponse[UserWithRoleResponse])
async def list_users(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.users.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PaginatedApiResponse[UserWithRoleResponse]:
    """Every account that can sign in, and its role here (admin only).

    **Not scoped to the clinic, on purpose.** Every other query filters by
    ``clinic_id`` (`CLAUDE.md`); this one cannot, because the thing an
    admin needs to see is precisely the account that is *not* in their
    clinic and can still log in. ``/auth/login`` never required a
    membership, so a user stranded outside the clinic keeps a working
    password while being absent from the only screen that could
    deactivate it.

    That is how a live server ended up with an invisible, working login:
    a deployment holds one clinic — nothing creates a second but
    ``/auth/setup`` and ``seed_demo.py`` — and seeding over an
    installation that already had one leaves its users behind a clinic
    the admin is no longer looking at.

    What crosses the boundary is bounded to what an operator must act on:
    who can sign in, whether they are active, and whether they have access
    here. Not which other clinic they belong to, nor their role in it.
    """
    memberships = (
        (
            await db.execute(
                select(ClinicMembership).where(ClinicMembership.clinic_id == ctx.clinic_id)
            )
        )
        .scalars()
        .all()
    )
    role_here = {m.user_id: m.role for m in memberships}

    # Every account, so one row per user rather than one per membership:
    # a user who belongs here *and* elsewhere is one person.
    all_users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()

    users = [
        UserWithRoleResponse(
            id=u.id,
            email=u.email,
            first_name=u.first_name,
            last_name=u.last_name,
            is_active=u.is_active,
            role=role_here.get(u.id),
            has_clinic_access=u.id in role_here,
            created_at=u.created_at.isoformat(),
        )
        for u in all_users
    ]

    return PaginatedApiResponse(
        data=users,
        total=len(users),
        page=1,
        page_size=len(users),
    )


@router.post(
    "/users", response_model=ApiResponse[UserResponse], status_code=status.HTTP_201_CREATED
)
async def create_user(
    data: UserCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.users.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[UserResponse]:
    """Create a new user (admin only)."""
    # Validate role
    if data.role not in ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role. Must be one of: {', '.join(ROLES)}",
        )

    # Validate password strength
    is_valid, error_msg = validate_password_strength(data.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_msg,
        )

    # Resolve the target clinic. A caller may only create a membership in
    # a clinic they administer themselves — otherwise an admin of clinic A
    # could mint an admin membership in clinic B by passing its id.
    clinic_id = data.clinic_id if data.clinic_id else ctx.clinic_id
    if clinic_id != ctx.clinic_id:
        caller_is_admin = await db.execute(
            select(ClinicMembership.id).where(
                ClinicMembership.user_id == ctx.user_id,
                ClinicMembership.clinic_id == clinic_id,
                ClinicMembership.role == "admin",
            )
        )
        if caller_is_admin.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not administer the target clinic",
            )

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    await ensure_user_room(db, clinic_id)

    # Create user
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
    )
    db.add(user)
    await db.flush()

    # Create clinic membership
    membership = ClinicMembership(
        user_id=user.id,
        clinic_id=clinic_id,
        role=data.role,
    )
    db.add(membership)
    await db.commit()

    return ApiResponse(data=UserResponse.model_validate(user))


@router.put("/users/{user_id}", response_model=ApiResponse[UserWithRoleResponse])
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.users.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[UserWithRoleResponse]:
    """Update a user in the current clinic (admin only)."""
    # Verify user belongs to this clinic
    result = await db.execute(
        select(ClinicMembership)
        .options(selectinload(ClinicMembership.user))
        .where(ClinicMembership.user_id == user_id)
        .where(ClinicMembership.clinic_id == ctx.clinic_id)
    )
    membership = result.scalar_one_or_none()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in this clinic",
        )

    user = membership.user

    # Prevent admin from deactivating themselves
    if data.is_active is False and user.id == ctx.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    # Validate role if provided
    if data.role is not None and data.role not in ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role. Must be one of: {', '.join(ROLES)}",
        )

    # Check email uniqueness if changing email
    if data.email is not None and data.email != user.email:
        email_check = await db.execute(select(User).where(User.email == data.email))
        if email_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        user.email = data.email

    # Update user fields
    if data.first_name is not None:
        user.first_name = data.first_name
    if data.last_name is not None:
        user.last_name = data.last_name
    if data.is_active is not None:
        user.is_active = data.is_active
        # Increment token version to invalidate existing tokens when deactivating
        if not data.is_active:
            user.token_version += 1

    # Update role in membership
    if data.role is not None:
        membership.role = data.role

    await db.commit()
    await db.refresh(user)
    await db.refresh(membership)

    return ApiResponse(
        data=UserWithRoleResponse(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            role=membership.role,
            created_at=user.created_at.isoformat(),
        )
    )


@router.get("/professionals", response_model=PaginatedApiResponse[ProfessionalResponse])
async def list_professionals(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("agenda.appointments.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PaginatedApiResponse[ProfessionalResponse]:
    """List professionals (dentists and hygienists) in the current clinic."""
    # Fetch memberships with dentist/hygienist role and active users
    result = await db.execute(
        select(ClinicMembership)
        .options(selectinload(ClinicMembership.user))
        .where(
            ClinicMembership.clinic_id == ctx.clinic_id,
            ClinicMembership.role.in_(["dentist", "hygienist"]),
        )
    )
    memberships = result.scalars().all()

    professionals = [
        ProfessionalResponse(
            id=m.user.id,
            email=m.user.email,
            first_name=m.user.first_name,
            last_name=m.user.last_name,
            role=m.role,
        )
        for m in memberships
        if m.user.is_active
    ]

    return PaginatedApiResponse(
        data=professionals,
        total=len(professionals),
        page=1,
        page_size=len(professionals),
    )


@router.patch("/users/{user_id}/active", response_model=ApiResponse[UserWithRoleResponse])
async def set_user_active(
    user_id: UUID,
    data: UserAccessUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.users.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[UserWithRoleResponse]:
    """Turn sign-in on or off for an account with no access to this clinic.

    The companion to listing those accounts (`GET /users`). Refusing them
    at login covers the ones that belong to no clinic at all; it cannot
    reach one stranded in *another* clinic row, which is what seeding over
    an existing installation leaves behind. Only an operator can decide
    such an account should stop working, so this is the operator's switch.

    **Deliberately narrow.** It sets one flag and nothing else: not the
    name, not the email, not a role. Editing the details of somebody who
    is not this clinic's staff is not an operator decision, and granting
    them a role here is `POST /users` or `PUT /users/{id}`.

    It assumes what the product already assumes: one clinic per
    deployment. Nothing creates a second but `/auth/setup` and
    `seed_demo.py`, so an account outside this clinic is residue of the
    same installation rather than another tenant's staff.
    """
    if user_id == ctx.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own access",
        )

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    member_here = (
        await db.execute(
            select(ClinicMembership)
            .where(ClinicMembership.user_id == user_id)
            .where(ClinicMembership.clinic_id == ctx.clinic_id)
        )
    ).scalar_one_or_none()
    if member_here is not None:
        # One way to do a thing: this clinic's staff are managed through the
        # endpoint that also carries their role and profile.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This user belongs to your clinic; update them with PUT /auth/users/{id}",
        )

    user.is_active = data.is_active
    if not data.is_active:
        # Same switch `update_user` throws: access tokens are stateless and
        # live 15 minutes, and this is what stops the one already issued.
        # The refresh path checks `is_active` on its own.
        user.token_version += 1
    await db.commit()
    await db.refresh(user)

    return ApiResponse(
        data=UserWithRoleResponse(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            role=None,
            has_clinic_access=False,
            created_at=user.created_at.isoformat(),
        )
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.users.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Remove a user from the current clinic (admin only).

    This removes the clinic membership but does not delete the user account.
    """
    # Prevent admin from removing themselves
    if user_id == ctx.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove yourself from the clinic",
        )

    # Verify user belongs to this clinic
    result = await db.execute(
        select(ClinicMembership)
        .where(ClinicMembership.user_id == user_id)
        .where(ClinicMembership.clinic_id == ctx.clinic_id)
    )
    membership = result.scalar_one_or_none()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in this clinic",
        )

    await db.delete(membership)
    await db.commit()


# --- Clinic metadata (B.5: moved from clinical module) ------------------


@router.get("/clinics", response_model=PaginatedApiResponse[ClinicMetadataResponse])
async def list_user_clinics(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
) -> PaginatedApiResponse[ClinicMetadataResponse]:
    """List the caller's active clinic with full metadata + cabinets."""
    clinics = [ClinicMetadataResponse.model_validate(ctx.clinic)]
    return PaginatedApiResponse(
        data=clinics,
        total=len(clinics),
        page=1,
        page_size=len(clinics),
    )


@router.get("/clinics/{clinic_id}", response_model=ApiResponse[ClinicMetadataResponse])
async def get_clinic_metadata(
    clinic_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
) -> ApiResponse[ClinicMetadataResponse]:
    """Get clinic details."""
    if ctx.clinic_id != clinic_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this clinic",
        )
    return ApiResponse(data=ClinicMetadataResponse.model_validate(ctx.clinic))


@router.put("/clinics", response_model=ApiResponse[ClinicMetadataResponse])
async def update_clinic_metadata(
    data: ClinicMetadataUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ClinicMetadataResponse]:
    """Update clinic info (admin only)."""
    clinic = ctx.clinic

    if data.name is not None:
        clinic.name = data.name
    if data.tax_id is not None:
        clinic.tax_id = data.tax_id
    if data.legal_name is not None:
        clinic.legal_name = data.legal_name or None
    if data.phone is not None:
        clinic.phone = data.phone
    if data.email is not None:
        clinic.email = data.email
    if data.address is not None:
        existing_address = clinic.address or {}
        new_address = data.address.model_dump(exclude_unset=True)
        clinic.address = {**existing_address, **new_address}
    if data.timezone is not None:
        clinic.timezone = data.timezone
    if data.currency is not None:
        clinic.currency = data.currency

    await db.commit()
    # Re-query with cabinets eagerly loaded so ClinicMetadataResponse
    # serialization doesn't trigger an async lazy load. The response
    # always returns the full metadata shape including cabinets.
    result = await db.execute(
        select(Clinic).where(Clinic.id == clinic.id).options(selectinload(Clinic.cabinets))
    )
    clinic = result.scalar_one()

    return ApiResponse(data=ClinicMetadataResponse.model_validate(clinic))


# ---------------------------------------------------------------------------
# Per-clinic settings (JSONB ``clinic.settings``).
#
# Module-specific settings live under namespaced keys so each module
# can read its own subset without colliding. The settings PATCH
# endpoint lives in core because ``Clinic`` is a core entity, but the
# accepted keys are validated against per-module schemas.
# ---------------------------------------------------------------------------


from pydantic import BaseModel, Field  # noqa: E402

from app.core.contracts import PatientDocuments, ProfessionalDirectory, provider  # noqa: E402
from app.core.letterhead import CLINIC as LETTERHEAD_CLINIC  # noqa: E402
from app.core.letterhead import (  # noqa: E402
    LOGO_MAX_BYTES,
    LetterheadWords,
    get_letterhead,
    logo_mime_type,
)
from app.core.tenancy.usage import by_clinical_kind, cached_file_usage  # noqa: E402

from .limits import clinic_limits, ensure_user_room  # noqa: E402
from .privacy_agreement import PRIVACY_AGREEMENT_VERSION, needs_renewal  # noqa: E402


class _BudgetSettingsPatch(BaseModel):
    """Subset of clinic.settings keys owned by the budget module."""

    budget_expiry_days: int | None = Field(default=None, ge=7, le=180)
    plan_auto_close_days_after_expiry: int | None = Field(default=None, ge=7, le=180)
    budget_reminders_enabled: bool | None = None
    budget_public_auth_disabled: bool | None = None


class _BudgetSettingsResponse(BaseModel):
    budget_expiry_days: int = 30
    plan_auto_close_days_after_expiry: int = 30
    budget_reminders_enabled: bool = False
    budget_public_auth_disabled: bool = False


def _read_budget_settings(raw: dict | None) -> _BudgetSettingsResponse:
    raw = raw or {}
    return _BudgetSettingsResponse(
        budget_expiry_days=int(raw.get("budget_expiry_days", 30)),
        plan_auto_close_days_after_expiry=int(raw.get("plan_auto_close_days_after_expiry", 30)),
        budget_reminders_enabled=bool(raw.get("budget_reminders_enabled", False)),
        budget_public_auth_disabled=bool(raw.get("budget_public_auth_disabled", False)),
    )


@router.get(
    "/clinic/settings/budget",
    response_model=ApiResponse[_BudgetSettingsResponse],
)
async def get_budget_settings(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
) -> ApiResponse[_BudgetSettingsResponse]:
    """Read the budget-related toggles from the clinic settings."""
    return ApiResponse(data=_read_budget_settings(ctx.clinic.settings))


@router.patch(
    "/clinic/settings/budget",
    response_model=ApiResponse[_BudgetSettingsResponse],
)
async def update_budget_settings(
    data: _BudgetSettingsPatch,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[_BudgetSettingsResponse]:
    """Update budget-related clinic settings (admin only)."""
    clinic = ctx.clinic
    current = dict(clinic.settings or {})
    payload = data.model_dump(exclude_unset=True)
    current.update(payload)
    clinic.settings = current
    await db.commit()
    await db.refresh(clinic)
    return ApiResponse(data=_read_budget_settings(clinic.settings))


# ---------------------------------------------------------------------------
# Home page layout (clinic-wide). The workspace App's first customisation
# (ADR 0043): which widgets the home page shows and in what order. Stored
# under ``home_layout``; the frontend applies it per slot, so the order is
# within each area of the page.
# ---------------------------------------------------------------------------

#: A widget id is a slot registration id: ``<module>.<slot>.<qualifier>``.
_WIDGET_ID = r"^[a-z][a-z0-9_]*(\.[A-Za-z0-9_-]+)+$"


class _HomeLayout(BaseModel):
    #: Widgets not shown. A widget left out of both lists is shown, in its
    #: own default place — so one added by a newly enabled App appears.
    hidden: list[Annotated[str, Field(pattern=_WIDGET_ID, max_length=120)]] = Field(
        default_factory=list, max_length=100
    )
    #: Display order. Applied within each area of the home page.
    order: list[Annotated[str, Field(pattern=_WIDGET_ID, max_length=120)]] = Field(
        default_factory=list, max_length=100
    )


def _read_home_layout(raw: dict | None) -> _HomeLayout:
    stored = (raw or {}).get("home_layout") or {}
    try:
        return _HomeLayout.model_validate(stored)
    except ValueError:
        # Whatever is stored and no longer parses is not worth a broken
        # home page: fall back to every widget in its default place.
        return _HomeLayout()


@router.get("/clinic/settings/home", response_model=ApiResponse[_HomeLayout])
async def get_home_layout(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
) -> ApiResponse[_HomeLayout]:
    """The home page layout. Every member's home page reads it, so it
    asks for no permission beyond belonging to the clinic."""
    return ApiResponse(data=_read_home_layout(ctx.clinic.settings))


@router.put("/clinic/settings/home", response_model=ApiResponse[_HomeLayout])
async def update_home_layout(
    data: _HomeLayout,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[_HomeLayout]:
    """Replace the home page layout (admin only). Empty lists restore the
    default: every widget, in the order its App gives it."""
    clinic = ctx.clinic
    clinic.settings = {
        **(clinic.settings or {}),
        "home_layout": {
            "hidden": list(dict.fromkeys(data.hidden)),
            "order": list(dict.fromkeys(data.order)),
        },
    }
    await db.commit()
    await db.refresh(clinic)
    return ApiResponse(data=_read_home_layout(clinic.settings))


# ---------------------------------------------------------------------------
# Brand (clinic-wide). The name and the logo the workspace shows in its
# sidebar, in place of the product's own (ADR 0043).
# ---------------------------------------------------------------------------


#: The accents and typefaces a clinic chooses from. A closed list each:
#: every accent ships with shades checked in light and dark, and every
#: typeface is served by the app itself — none is fetched from a third
#: party. The frontend holds what each key looks like
#: (`frontend/app/config/workspaceTheme.ts`); the first of each is the
#: product's own and is what ``None`` means.
BRAND_ACCENTS = ("sky", "teal", "emerald", "indigo", "violet", "rose", "orange", "slate")
BRAND_FONTS = ("inter", "source-sans", "nunito-sans", "plex-sans", "atkinson")

_Accent = Literal["sky", "teal", "emerald", "indigo", "violet", "rose", "orange", "slate"]
_Font = Literal["inter", "source-sans", "nunito-sans", "plex-sans", "atkinson"]
#: How round the corners are, and how tightly the interface is packed.
#: ``rounded`` and ``comfortable`` are the product's own.
BRAND_CORNERS = ("sharp", "rounded", "round")
BRAND_DENSITIES = ("comfortable", "compact")
_Corners = Literal["sharp", "rounded", "round"]
_Density = Literal["comfortable", "compact"]
#: The colour mode the workspace opens in for whoever has not chosen their
#: own. ``system`` follows the device. ``light`` is the product's own.
BRAND_COLOR_MODES = ("light", "dark", "system")
_ColorMode = Literal["light", "dark", "system"]


class _BrandWords(BaseModel):
    #: Shown next to the logo. Empty: the product's name.
    display_name: str | None = Field(default=None, max_length=60)
    #: The colour of buttons, links and highlights. ``None``: the product's.
    accent: _Accent | None = None
    #: The typeface of the whole interface. ``None``: the product's.
    font: _Font | None = None
    #: Corner roundness of cards, buttons and fields. ``None``: the product's.
    corners: _Corners | None = None
    #: ``compact`` packs the interface tighter — with a mouse only: on a
    #: touch screen the tap targets keep their size (ADR 0022).
    density: _Density | None = None
    #: A default, not a rule: each person keeps their own light/dark switch.
    color_mode: _ColorMode | None = None


class _BrandResponse(_BrandWords):
    #: Whether the clinic uploaded a logo. The image is fetched apart.
    has_logo: bool = False


async def _brand_response(db: AsyncSession, clinic: Clinic) -> _BrandResponse:
    stored = (clinic.settings or {}).get("brand") or {}
    name = stored.get("display_name")
    accent, font = stored.get("accent"), stored.get("font")
    return _BrandResponse(
        display_name=name if isinstance(name, str) and name.strip() else None,
        # A stored key the product no longer offers falls back to its own.
        accent=accent if accent in BRAND_ACCENTS else None,
        font=font if font in BRAND_FONTS else None,
        corners=stored.get("corners") if stored.get("corners") in BRAND_CORNERS else None,
        density=stored.get("density") if stored.get("density") in BRAND_DENSITIES else None,
        color_mode=(
            stored.get("color_mode") if stored.get("color_mode") in BRAND_COLOR_MODES else None
        ),
        has_logo=await db.get(ClinicBrandLogo, clinic.id) is not None,
    )


class _FileTypeUsageResponse(BaseModel):
    model_config = {"from_attributes": True}

    #: A clinical kind as media names it (``xray``, ``photo``, ``document``…),
    #: ``previews`` (reduced copies of images) or ``other``.
    type: str
    bytes: int
    count: int


class _StorageUsageResponse(BaseModel):
    #: Everything the clinics uploaded, with the reduced copies of its images.
    total_bytes: int
    file_count: int
    types: list[_FileTypeUsageResponse]
    #: When the files were last counted: the figure is kept for ten minutes.
    measured_at: datetime


@router.get("/tenant/storage", response_model=ApiResponse[_StorageUsageResponse])
async def get_storage_usage(
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
    refresh: bool = False,
) -> ApiResponse[_StorageUsageResponse]:
    """Disk space the tenant's uploaded files take up, by clinical kind.

    A figure of the tenant, not of the clinic asking: clinics share its
    storage. Counted at most once every ten minutes; ``refresh=true``
    counts again now.
    """
    root = Path(settings.STORAGE_LOCAL_PATH) / tenant.storage_prefix
    measured = await cached_file_usage(root, refresh=refresh)
    # With the Media App off nobody can say what a file is: it all goes
    # under "other".
    documents = provider(PatientDocuments)
    kinds = await documents.usage_by_kind(db) if documents else []
    return ApiResponse(
        data=_StorageUsageResponse(
            total_bytes=measured.usage.total_bytes,
            file_count=measured.usage.file_count,
            types=[
                _FileTypeUsageResponse.model_validate(t)
                for t in by_clinical_kind(measured.usage, kinds)
            ],
            measured_at=measured.measured_at,
        )
    )


class _PrivacyAcceptance(BaseModel):
    #: The version of the agreement that was on the screen.
    version: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._-]+$")


@router.post("/clinic/onboarding/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_privacy_agreement(
    data: _PrivacyAcceptance,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
) -> None:
    """The holder accepts the privacy agreement: the welcome is over. Kept
    with the date is the version of the text they were shown, which has
    to be the one in force — a page loaded before the text changed is
    refused, and shows the current text once reloaded."""
    if data.version != PRIVACY_AGREEMENT_VERSION:
        raise HTTPException(status.HTTP_409_CONFLICT, "Not the privacy agreement in force")
    ctx.clinic.privacy_accepted_at = datetime.now(UTC)
    ctx.clinic.privacy_accepted_version = data.version
    ctx.clinic.privacy_declined_at = None
    ctx.clinic.onboarding_pending = False


@router.post("/clinic/onboarding/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_privacy_agreement(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
) -> None:
    """The holder declines the privacy agreement and loses access: the
    clinic is deactivated, which closes it to its members until the
    operator reactivates it. Only while there is an agreement to answer:
    the welcome is pending, or the one accepted is no longer in force. In
    the second case the clinic is in use, and it closes to all its staff."""
    if not (ctx.clinic.onboarding_pending or needs_renewal(ctx.clinic)):
        raise HTTPException(status.HTTP_409_CONFLICT, "The privacy agreement was already accepted")
    ctx.clinic.deactivated_at = ctx.clinic.privacy_declined_at = datetime.now(UTC)


class _ClinicLimitsResponse(BaseModel):
    model_config = {"from_attributes": True}

    users: int
    #: The holder and the users the clinic may add; ``None`` is no limit.
    users_limit: int | None
    storage_bytes: int
    storage_limit_bytes: int | None


@router.get("/clinic/limits", response_model=ApiResponse[_ClinicLimitsResponse])
async def get_clinic_limits(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> ApiResponse[_ClinicLimitsResponse]:
    """What the clinic's account tier allows it, beside what it uses: its
    users and the disk its files take."""
    limits = await clinic_limits(db, tenant, ctx.clinic_id)
    return ApiResponse(data=_ClinicLimitsResponse.model_validate(limits))


@router.get("/clinic/settings/brand", response_model=ApiResponse[_BrandResponse])
async def get_brand(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[_BrandResponse]:
    """The workspace's name and whether it has a logo. Every member's
    sidebar reads it, so it asks for no permission beyond belonging to the
    clinic."""
    return ApiResponse(data=await _brand_response(db, ctx.clinic))


@router.put("/clinic/settings/brand", response_model=ApiResponse[_BrandResponse])
async def update_brand(
    data: _BrandWords,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[_BrandResponse]:
    """Set the workspace's name, accent and typeface. An empty value
    restores the product's."""
    clinic = ctx.clinic
    name = (data.display_name or "").strip() or None
    clinic.settings = {
        **(clinic.settings or {}),
        "brand": {**data.model_dump(), "display_name": name},
    }
    await db.commit()
    await db.refresh(clinic)
    return ApiResponse(data=await _brand_response(db, clinic))


@router.get("/clinic/settings/brand/logo")
async def get_brand_logo(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """The workspace's logo, for every member's sidebar."""
    logo = await db.get(ClinicBrandLogo, ctx.clinic_id)
    if logo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No logo")
    return Response(content=logo.image, media_type=logo.mime_type)


@router.put("/clinic/settings/brand/logo", status_code=status.HTTP_204_NO_CONTENT)
async def put_brand_logo(
    file: Annotated[UploadFile, File()],
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Set the workspace's logo: a PNG or JPEG of at most 512 KB. The type
    is read from the file's own first bytes."""
    image = await file.read(LOGO_MAX_BYTES + 1)
    if len(image) > LOGO_MAX_BYTES:
        raise HTTPException(status_code=400, detail="The logo must be 512 KB or smaller")
    mime_type = logo_mime_type(image)
    if mime_type is None:
        raise HTTPException(status_code=400, detail="The logo must be a PNG or JPEG image")

    logo = await db.get(ClinicBrandLogo, ctx.clinic_id)
    if logo is None:
        db.add(ClinicBrandLogo(clinic_id=ctx.clinic_id, image=image, mime_type=mime_type))
    else:
        logo.image, logo.mime_type = image, mime_type
    await db.commit()


@router.delete("/clinic/settings/brand/logo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand_logo(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Go back to the product's own mark."""
    logo = await db.get(ClinicBrandLogo, ctx.clinic_id)
    if logo is not None:
        await db.delete(logo)
        await db.commit()


# ---------------------------------------------------------------------------
# Letterheads. What heads every printed clinical document: the clinic's
# own, and one per professional who wants theirs (ADR 0046).
# ---------------------------------------------------------------------------


class _LetterheadResponse(LetterheadWords):
    #: Whose it is: ``None`` is the clinic's own.
    professional_id: UUID | None = None
    #: Whether a logo is on file. The image itself is fetched apart.
    has_logo: bool = False


def _letterhead_response(row: ClinicLetterhead) -> _LetterheadResponse:
    return _LetterheadResponse(
        **LetterheadWords.model_validate(row, from_attributes=True).model_dump(),
        professional_id=None if row.owner_key == LETTERHEAD_CLINIC else UUID(row.owner_key),
        has_logo=row.logo_mime_type is not None,
    )


async def _letterhead_owner(db: AsyncSession, clinic_id: UUID, owner: str) -> str:
    """``clinic``, or a professional of this clinic's directory.

    A letterhead for somebody who is not one of the clinic's professionals
    would be a head no document could ever carry.
    """
    if owner == LETTERHEAD_CLINIC:
        return owner
    try:
        professional_id = UUID(owner)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Letterhead not found") from error
    directory = provider(ProfessionalDirectory)
    if directory is None or professional_id not in await directory.briefs(
        db, clinic_id, [professional_id]
    ):
        raise HTTPException(status_code=404, detail="Professional not found in this clinic")
    return str(professional_id)


async def _own_professional(db: AsyncSession, ctx: ClinicContext) -> UUID | None:
    """The directory profile the acting account *is*, if it has one."""
    directory = provider(ProfessionalDirectory)
    return await directory.for_account(db, ctx.clinic_id, ctx.user_id) if directory else None


async def _may_touch_letterhead(
    db: AsyncSession, ctx: ClinicContext, owner: str, *, write: bool
) -> None:
    """Whoever runs the clinic's settings, or the professional it belongs to.

    A doctor keeps their own letterhead — theirs and nobody else's: not the
    clinic's, not a colleague's.
    """
    if has_permission(ctx.role, "admin.clinic.write" if write else "admin.clinic.read"):
        return
    mine = await _own_professional(db, ctx)
    if mine is None or owner != str(mine):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the clinic's administrators or the professional it belongs to",
        )


class _OwnLetterheadResponse(BaseModel):
    """What the acting account may set up for itself."""

    #: ``None``: this account is not one of the clinic's professionals.
    professional_id: UUID | None = None
    #: Offered as the extra line of a letterhead being created.
    suggested_subheading: str | None = None
    letterhead: _LetterheadResponse | None = None


@router.get("/clinic/settings/letterheads/mine", response_model=ApiResponse[_OwnLetterheadResponse])
async def get_own_letterhead(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[_OwnLetterheadResponse]:
    """The acting professional's own letterhead, if they are one and have one."""
    mine = await _own_professional(db, ctx)
    if mine is None:
        return ApiResponse(data=_OwnLetterheadResponse())
    directory = provider(ProfessionalDirectory)
    brief = (await directory.briefs(db, ctx.clinic_id, [mine])).get(mine) if directory else None
    suggested = None
    if brief is not None:
        suggested = " · ".join(
            filter(None, [f"{brief.first_name} {brief.last_name}".strip(), brief.license_number])
        )
    row = await get_letterhead(db, ctx.clinic_id, str(mine))
    return ApiResponse(
        data=_OwnLetterheadResponse(
            professional_id=mine,
            suggested_subheading=suggested,
            letterhead=_letterhead_response(row) if row is not None else None,
        )
    )


async def _letterhead_row(
    db: AsyncSession, clinic_id: UUID, owner: str, *, create: bool, with_logo: bool = False
) -> ClinicLetterhead:
    key = await _letterhead_owner(db, clinic_id, owner)
    row = await get_letterhead(db, clinic_id, key, with_logo=with_logo)
    if row is None:
        if not create:
            raise HTTPException(status_code=404, detail="Letterhead not found")
        row = ClinicLetterhead(clinic_id=clinic_id, owner_key=key)
        db.add(row)
    return row


@router.get("/clinic/settings/letterheads", response_model=ApiResponse[list[_LetterheadResponse]])
async def list_letterheads(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[_LetterheadResponse]]:
    """The clinic's letterhead and each professional's, clinic first."""
    rows = (
        await db.execute(
            select(ClinicLetterhead).where(ClinicLetterhead.clinic_id == ctx.clinic_id)
        )
    ).scalars()
    ordered = sorted(rows, key=lambda row: (row.owner_key != LETTERHEAD_CLINIC, row.created_at))
    return ApiResponse(data=[_letterhead_response(row) for row in ordered])


@router.put("/clinic/settings/letterheads/{owner}", response_model=ApiResponse[_LetterheadResponse])
@declares_permissions("admin.clinic.write")
async def save_letterhead(
    owner: str,
    data: LetterheadWords,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[_LetterheadResponse]:
    """Write the words of a letterhead: ``clinic``, or a professional's id.
    Created on first save."""
    await _may_touch_letterhead(db, ctx, owner, write=True)
    row = await _letterhead_row(db, ctx.clinic_id, owner, create=True)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return ApiResponse(data=_letterhead_response(row))


@router.delete("/clinic/settings/letterheads/{owner}", status_code=status.HTTP_204_NO_CONTENT)
@declares_permissions("admin.clinic.write")
async def delete_letterhead(
    owner: str,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Remove a letterhead. That professional's documents go back to the
    clinic's; removing the clinic's leaves its bare name."""
    await _may_touch_letterhead(db, ctx, owner, write=True)
    row = await _letterhead_row(db, ctx.clinic_id, owner, create=False)
    await db.delete(row)
    await db.commit()


@router.get("/clinic/settings/letterheads/{owner}/logo")
@declares_permissions("admin.clinic.read")
async def get_letterhead_logo(
    owner: str,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await _may_touch_letterhead(db, ctx, owner, write=False)
    row = await _letterhead_row(db, ctx.clinic_id, owner, create=False, with_logo=True)
    if not row.logo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No logo")
    return Response(content=row.logo, media_type=row.logo_mime_type)


@router.put("/clinic/settings/letterheads/{owner}/logo", status_code=status.HTTP_204_NO_CONTENT)
@declares_permissions("admin.clinic.write")
async def put_letterhead_logo(
    owner: str,
    file: Annotated[UploadFile, File()],
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Set a letterhead's logo: a PNG or JPEG of at most 512 KB."""
    await _may_touch_letterhead(db, ctx, owner, write=True)
    image = await file.read(LOGO_MAX_BYTES + 1)
    if len(image) > LOGO_MAX_BYTES:
        raise HTTPException(status_code=400, detail="The logo must be 512 KB or smaller")
    mime_type = logo_mime_type(image)
    if mime_type is None:
        raise HTTPException(status_code=400, detail="The logo must be a PNG or JPEG image")

    row = await _letterhead_row(db, ctx.clinic_id, owner, create=True)
    row.logo, row.logo_mime_type = image, mime_type
    await db.commit()


@router.delete("/clinic/settings/letterheads/{owner}/logo", status_code=status.HTTP_204_NO_CONTENT)
@declares_permissions("admin.clinic.write")
async def delete_letterhead_logo(
    owner: str,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Print that letterhead without a logo again."""
    await _may_touch_letterhead(db, ctx, owner, write=True)
    row = await _letterhead_row(db, ctx.clinic_id, owner, create=False)
    row.logo, row.logo_mime_type = None, None
    await db.commit()


# ---------------------------------------------------------------------------
# Communications settings (clinic-wide). Drives the language used for
# patient-facing pages (public budget link), email templates, and
# future SMS / WhatsApp messages.
# ---------------------------------------------------------------------------


class _CommunicationsSettingsPatch(BaseModel):
    language: str | None = Field(default=None, pattern="^(es|en)$")


class _CommunicationsSettingsResponse(BaseModel):
    language: str = "es"


def _read_communications_settings(raw: dict | None) -> _CommunicationsSettingsResponse:
    raw = raw or {}
    return _CommunicationsSettingsResponse(
        language=str(raw.get("communication_language", "es")),
    )


@router.get(
    "/clinic/settings/communications",
    response_model=ApiResponse[_CommunicationsSettingsResponse],
)
async def get_communications_settings(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
) -> ApiResponse[_CommunicationsSettingsResponse]:
    """Read the clinic-wide communications language."""
    return ApiResponse(data=_read_communications_settings(ctx.clinic.settings))


@router.patch(
    "/clinic/settings/communications",
    response_model=ApiResponse[_CommunicationsSettingsResponse],
)
async def update_communications_settings(
    data: _CommunicationsSettingsPatch,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[_CommunicationsSettingsResponse]:
    """Update the clinic-wide communications language.

    Persists under ``clinic.settings.communication_language``.
    """
    clinic = ctx.clinic
    current = dict(clinic.settings or {})
    if data.language is not None:
        current["communication_language"] = data.language
    clinic.settings = current
    await db.commit()
    await db.refresh(clinic)
    return ApiResponse(data=_read_communications_settings(clinic.settings))
