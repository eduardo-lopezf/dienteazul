"""Authentication dependencies for FastAPI."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.log_context import set_request_context
from app.database import get_db

from .models import AuthSession, Clinic, ClinicMembership, User
from .permissions import has_permission
from .service import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class ClinicContext:
    """Context object containing current user and clinic."""

    def __init__(self, user: User, clinic: Clinic, role: str):
        self.user = user
        self.clinic = clinic
        self.role = role
        self.clinic_id = clinic.id
        self.user_id = user.id


async def get_current_user(
    request: Request,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Get current authenticated user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        token_type = payload.get("type")
        token_version = payload.get("token_version", 0)
        raw_family_id = payload.get("family_id")

        if user_id is None or token_type != "access":
            raise credentials_exception

    except PyJWTError:
        raise credentials_exception

    # Fetch user from database
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # Check token version for revocation
    if user.token_version != token_version:
        raise credentials_exception

    family_id: UUID | None = None
    if raw_family_id is None:
        # Tokens minted before family claims were introduced have at
        # most their original 15-minute access lifetime to transition.
        issued_at = payload.get("iat")
        if issued_at is None:
            expires_at = payload.get("exp")
            if not isinstance(expires_at, (int, float)):
                raise credentials_exception
            issued_at = expires_at - settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        try:
            issued = datetime.fromtimestamp(float(issued_at), UTC)
        except (TypeError, ValueError, OverflowError):
            raise credentials_exception from None
        now = datetime.now(UTC)
        if issued > now or issued < now - timedelta(minutes=15):
            raise credentials_exception
    else:
        try:
            family_id = UUID(raw_family_id)
        except (TypeError, ValueError):
            raise credentials_exception from None

        result = await db.execute(
            select(AuthSession)
            .where(
                AuthSession.family_id == family_id,
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
            .limit(1)
            .execution_options(populate_existing=True)
        )
        session = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if (
            session is None
            or session.family_expires_at <= now
            or session.last_activity_at
            + timedelta(minutes=settings.AUTH_SESSION_IDLE_TIMEOUT_MINUTES)
            <= now
        ):
            raise credentials_exception

    request.state.auth_family_id = family_id

    return user


#: What the welcome of a new clinic uses (``/onboarding``): the clinic's
#: own details and its acceptance, its hours and its cabinets, and the
#: list of Apps the frontend starts from. Paths, not imports — core knows
#: where the two settings pages of the welcome call, nothing of the
#: modules behind them. A step added to the welcome adds its prefix here.
ONBOARDING_OPEN = (
    "/api/v1/auth/clinic",
    "/api/v1/modules/-/active",
    "/api/v1/schedules/clinic-",
    "/api/v1/agenda/cabinets",
)


async def get_clinic_context(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    clinic_id: UUID | None = None,
) -> ClinicContext:
    """Get clinic context for the current user.

    If clinic_id is not provided, uses the user's first clinic.
    Raises 403 if user doesn't have access to the clinic.
    """
    # An account still on a password somebody else gave it may read its
    # own profile and change that password (both resolve the user only);
    # everything that needs a clinic waits until it has.
    if current_user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required",
        )

    # Get user's clinic memberships; eager-load cabinets so downstream
    # ClinicResponse.model_validate doesn't trigger async lazy loads.
    from app.core.auth.models import Clinic as ClinicModel

    result = await db.execute(
        select(ClinicMembership)
        .options(selectinload(ClinicMembership.clinic).selectinload(ClinicModel.cabinets))
        .where(ClinicMembership.user_id == current_user.id)
        # Oldest first, as on ``User.memberships``: "the first clinic"
        # below has to mean the same one on every request.
        .order_by(ClinicMembership.created_at)
    )
    memberships = result.scalars().all()

    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any clinic",
        )

    # A deactivated clinic is closed to its members; the ones they have in
    # other clinics are not.
    memberships = [m for m in memberships if m.clinic.deactivated_at is None]
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This clinic has been deactivated",
        )

    # Find the requested clinic or use the first one
    if clinic_id:
        membership = next(
            (m for m in memberships if m.clinic_id == clinic_id),
            None,
        )
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have access to this clinic",
            )
    else:
        membership = memberships[0]

    # A clinic has the Apps chosen for it and no others. A module's routes
    # live under ``/api/v1/<module>``; one that belongs to an App the
    # clinic does not have answers as it would if the deployment had the
    # App switched off — not found — which is what the app already knows
    # how to live with (ADR 0038).
    from app.core.plugins.apps import modules_outside

    # A clinic whose holder has not been through the welcome is open only
    # to what the welcome itself uses, until the privacy agreement is
    # accepted. The frontend takes the holder there; this is what holds
    # whoever does not come through the frontend.
    # The same holds its administrators when the agreement they accepted is
    # no longer the one in force; the rest of its staff works on.
    from .privacy_agreement import needs_renewal

    held = membership.clinic.onboarding_pending or (
        membership.role == "admin" and needs_renewal(membership.clinic)
    )
    if held and not request.url.path.startswith(ONBOARDING_OPEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Onboarding required",
        )

    segments = request.url.path.split("/")
    if len(segments) > 3 and segments[3] in modules_outside(membership.clinic.apps):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    # Bind clinic_id + user_id onto the per-request logging context so
    # every log line and event emitted inside this handler carries
    # them automatically (request_id was set by the middleware). Not
    # reset — the middleware drops the whole context at request end.
    set_request_context(clinic_id=membership.clinic.id, user_id=current_user.id)

    return ClinicContext(
        user=current_user,
        clinic=membership.clinic,
        role=membership.role,
    )


# Attribute carrying the permissions a route is gated by, readable
# without executing the route. ``tests/test_route_authorization_coverage.py``
# walks every mounted route looking for it (ADR 0029, invariant 1).
PERMISSION_MARKER = "__dienteazul_permissions__"


def require_permission(permission: str) -> Callable:
    """FastAPI dependency factory that requires a specific permission.

    Usage:
        @router.get("/patients")
        async def list_patients(
            ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
            _: Annotated[None, Depends(require_permission("clinical.patients.read"))],
        ):
            ...
    """

    async def permission_checker(
        ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    ) -> None:
        if not has_permission(ctx.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission}",
            )

    # So the coverage test can read which permission gates the route
    # instead of inferring it from the closure.
    setattr(permission_checker, PERMISSION_MARKER, (permission,))
    return permission_checker


def declares_permissions(*permissions: str) -> Callable:
    """Mark a handler that checks its own permissions in the body.

    The dependency in :func:`require_permission` is the normal way, and
    it is preferred: it is declarative, it runs before the handler, and
    it cannot be skipped by an early ``return``. A handful of routes
    cannot use it, because *which* permission applies depends on the
    object being addressed — ``schedules`` picks between managing any
    professional's calendar and managing your own, and that is not known
    until the path parameter is resolved.

    Those routes are authorized; they are simply authorized somewhere a
    dependency scan cannot see. This decorator makes the enforcement
    **declared** rather than merely present, so the coverage test can
    tell them apart from a route nobody remembered to gate. It changes
    no behaviour — the handler still does the checking.

    Do not reach for this to silence the coverage test. A route whose
    permission is a constant belongs in ``require_permission``.
    """

    def decorate(handler: Callable) -> Callable:
        setattr(handler, PERMISSION_MARKER, tuple(permissions))
        return handler

    return decorate
