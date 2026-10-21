"""FastAPI application entry point."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.advisory_locks import BOOT_LOCK, advisory_lock
from app.core.auth.router import limiter
from app.core.auth.router import router as auth_router
from app.core.log_context import (
    new_request_id,
    reset_request_context,
    set_request_context,
    setup_logging,
)
from app.core.plugins.gate import API_PREFIX, module_gate
from app.core.plugins.loader import discover_and_register, mount_active
from app.core.plugins.processor import PendingProcessor
from app.core.plugins.registry import module_registry
from app.core.plugins.service import ModuleService, installed_module_names, sync_module_gate
from app.core.privacy import PrivacyPolicy, incompatible_tiers
from app.core.privacy.egress import log_egress_audit
from app.core.scheduler import init_scheduler, shutdown_scheduler
from app.core.schemas import ErrorResponse
from app.core.tenancy import SingleTenantResolver
from app.database import async_session_maker, commit_before_response, engine, get_db

logger = logging.getLogger(__name__)


async def _mount_installed_modules(app: FastAPI, skip: set[str] | None = None) -> None:
    """Give a runtime surface to the modules ``core_module`` says are live.

    If the state cannot be read at all, mount every discovered module
    and say so loudly. This is a clinic's working day: serving a module
    that should have been uninstalled beats refusing to serve anything.
    The ``exception`` log is the signal — the one thing this must never
    do is fail quietly (audit S5).
    """
    try:
        async with async_session_maker() as session:
            installed = await installed_module_names(session)
    except Exception:
        logger.exception(
            "Could not read module install state; falling back to mounting every discovered module"
        )
        installed = {module.name for module in module_registry.list_discovered()}

    if skip:
        blocked = installed & skip
        if blocked:
            logger.error(
                "Not mounting %s: their schema did not reach head this boot. "
                "The code is the new version and the tables are not — fix the "
                "migration and restart.",
                sorted(blocked),
            )
            installed -= blocked

    mount_active(app, installed)


async def _log_tier_custody_audit(policy: PrivacyPolicy) -> None:
    """Warn about clinics whose tier this deployment is not sold under.

    Reports rather than refuses: a boot that fails over a commercial rule
    would take a working clinic offline, which is the trade this codebase
    already declined for licence expiry (ADR 0028 rule 3).
    """
    from app.core.auth.models import Clinic

    try:
        async with async_session_maker() as session:
            tiers = (await session.scalars(select(Clinic.account_tier).distinct())).all()
    except Exception:
        logger.exception("Could not read clinic tiers for the custody audit")
        return

    offenders = incompatible_tiers(tiers, policy.custody_mode)
    if offenders:
        logger.warning(
            "Custody audit: custody mode %r does not serve account tier(s) %s, "
            "but clinics exist under them. Either the mode or those clinics are wrong.",
            policy.custody_mode.value,
            ", ".join(repr(tier) for tier in offenders),
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup and shutdown."""
    # Logging: attach the context filter early so every line emitted
    # during startup / module install also carries the bound fields
    # (defaults to ``-`` outside a request).
    setup_logging()

    # Startup.
    #
    # The order is load-bearing (audit S1). Discovery only fills the
    # registry — it mounts nothing — so the database gets to decide what
    # runs. Mounting first, as this used to, meant an uninstalled module
    # kept its routes, its event handlers, its copilot tools and its
    # permission grants no matter what ``core_module`` said.
    module_gate.clear()
    discover_and_register()

    # The two steps below write: rows in ``core_module``, module
    # migrations, and an uninstall's ``DROP TABLE``. One replica at a time
    # — the next one waits here, then reads a registry with nothing left
    # pending.
    failed_migrations: set[str] = set()
    async with advisory_lock(BOOT_LOCK):
        # Sync in-memory registry into core_module (best-effort).
        try:
            async with async_session_maker() as session:
                await ModuleService(session).reconcile_with_db()
        except Exception:
            logger.exception("Module registry reconciliation failed at startup")

        # Process pending install/uninstall/upgrade operations. Running
        # this before mounting is what lets an install go live on the same
        # boot that schedules it, instead of needing a second restart.
        try:
            processor = PendingProcessor(async_session_maker)
            processed = await processor.run()
            failed_migrations = processor.failed_migrations
            if processed:
                logger.info("Processed pending module operations: %s", processed)
        except Exception:
            logger.exception("Pending module processor raised")

    await _mount_installed_modules(app, skip=failed_migrations)

    # Tenant resolution. Built after mounting so ``modules_enabled``
    # reflects the active set, not everything discovered on disk. A SaaS
    # module replaces this with its own resolver (ADR 0012 §4); the
    # self-hosted one carries the ``self`` custody policy (ADR 0023).
    app.state.tenant_resolver = SingleTenantResolver()

    # Say, once, which modules reach a destination the policy has not
    # permitted. A warning rather than a refusal — see ADR 0027.
    policy = (await app.state.tenant_resolver.resolve_by_slug("default")).privacy
    log_egress_audit(policy)

    # And say, once, whether any clinic is running under a tier this
    # deployment's custody mode does not serve. The pair is validated at
    # creation, but the custody half is an environment variable and can be
    # changed under clinics that already exist.
    await _log_tier_custody_audit(policy)

    # Initialize scheduler for background jobs (installed modules only —
    # ``module_registry.list_modules()`` is the active set).
    init_scheduler()

    yield

    # Shutdown
    shutdown_scheduler()
    await engine.dispose()


app = FastAPI(
    title="Diente Azul API",
    description="Open source dental clinic management software",
    version="2.0.0",
    lifespan=lifespan,
    redirect_slashes=False,
    # Every route, module routers included: they are mounted onto
    # ``app.router`` and inherit its dependencies.
    dependencies=[Depends(commit_before_response, scope="function")],
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT == "development" else None,
)

# Configure rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Configure CORS
allowed_origins = settings.allowed_origins_list.copy()
if settings.ENVIRONMENT == "development":
    allowed_origins.extend(
        [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Paths whose response is an HTML page rather than JSON, and which
# therefore cannot live under ``default-src 'none'``. Both are Swagger /
# ReDoc, both load their assets from a CDN, and both are mounted only
# when ``ENVIRONMENT == "development"`` — so in production this set is
# never matched.
_HTML_DOC_PATHS: frozenset[str] = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})

# One policy for an API that returns JSON and nothing else. ``'none'``
# rather than ``'self'`` because there is no legitimate subresource a
# response from this app should ever pull: if a browser is executing
# something out of an API response, that is the incident.
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Attach the response headers that bound what a browser will do.

    The API had none of these (ADR 0029, invariant 4). They are cheap
    and each closes a specific door:

    - ``X-Content-Type-Options`` — stops a JSON response, or an uploaded
      file served by ``media``, from being sniffed into HTML and run.
    - ``Content-Security-Policy`` / ``X-Frame-Options`` — nothing loads,
      nothing frames. ``frame-ancestors`` is what modern browsers read;
      ``X-Frame-Options`` covers the ones that do not.
    - ``Referrer-Policy`` — the public budget URL carries its token in
      the path (ADR 0006), and a referrer header hands that token to
      whatever the page links out to.
    - ``X-Robots-Tag`` — ADR 0006 assumed this existed ("mitigated
      separately with ``noindex`` headers"). It did not. An API has no
      business in an index, so it is set unconditionally rather than
      per-route.
    - ``Strict-Transport-Security`` — production only, where TLS is a
      given. Sending it over plaintext development would pin localhost.

    Set after ``call_next`` and with ``setdefault``, so a handler that
    deliberately needs a different value keeps it.
    """
    response = await call_next(request)

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")

    if request.url.path not in _HTML_DOC_PATHS:
        response.headers.setdefault("Content-Security-Policy", _API_CSP)

    if settings.ENVIRONMENT == "production":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )

    return response


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Bind ``request_id`` for the lifetime of one HTTP request.

    Accepts an inbound ``X-Request-Id`` so a load balancer / client
    can correlate traces; otherwise mints a fresh short id. Echoes
    the value back on the response (success or error) so the caller
    can grep server logs. ``clinic_id`` / ``user_id`` are bound later
    by the auth dependency once they are known.
    """
    incoming = request.headers.get("x-request-id")
    rid = incoming if incoming and len(incoming) <= 64 else new_request_id()
    tokens = set_request_context(request_id=rid)
    try:
        response = await call_next(request)
    finally:
        reset_request_context(tokens)
    response.headers["X-Request-Id"] = rid
    return response


def _cors_headers(request: Request) -> dict[str, str]:
    # CORSMiddleware can't add headers to responses produced by exception
    # handlers (BaseHTTPMiddleware-based stacks lose the response when an
    # exception escapes). Without these headers, browsers report any 5xx
    # as a network error ("can't connect to server") instead of surfacing
    # the real status — which masks bugs and confuses users. So we mirror
    # CORSMiddleware's allow-list logic here for error responses.
    origin = request.headers.get("origin")
    if not origin:
        return {}
    if origin in allowed_origins or "*" in allowed_origins:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return {}


@app.middleware("http")
async def module_gate_middleware(request: Request, call_next):
    """Refuse traffic for a module that is on its way out.

    Lifecycle transitions take effect at the next restart, so between
    a disable or uninstall and that restart the module is still mounted.
    After an uninstall, anything written in that window lands in tables
    the processor is about to drop — backed up to a ``pg_dump`` file
    nobody will read. A ``409`` says so instead of pretending the write
    survived.

    Preflight requests pass through: answering ``OPTIONS`` with 409
    makes the browser report a CORS failure and hides the real status
    from the caller.

    The state usually changes in another process — the CLI, or another
    backend — so every few seconds one request stops to ask the database
    what it now says.
    """
    if request.method != "OPTIONS":
        if request.url.path.startswith(API_PREFIX):
            ticket = module_gate.claim_sync()
            if ticket is not None:
                await sync_module_gate(async_session_maker, ticket)

        blocked = module_gate.match(request.url.path)
        if blocked is not None:
            error = ErrorResponse(
                message=f"Module '{blocked}' is being turned off and no longer accepts requests.",
                errors=[f"module '{blocked}' pending deactivation"],
            )
            return JSONResponse(
                status_code=409,
                content=error.model_dump(),
                headers=_cors_headers(request),
            )

    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handler for HTTP exceptions using standard ErrorResponse format."""
    error_response = ErrorResponse(
        message=str(exc.detail),
        errors=[str(exc.detail)] if exc.detail else [],
    )
    headers = dict(exc.headers or {})
    headers.update(_cors_headers(request))
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(),
        headers=headers,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler for unhandled errors."""
    logger.exception("Unhandled exception", exc_info=exc)
    if settings.ENVIRONMENT == "development":
        error_response = ErrorResponse(
            message=str(exc),
            errors=[str(exc)],
        )
    else:
        error_response = ErrorResponse(
            message="Internal server error",
            errors=[],
        )
    return JSONResponse(
        status_code=500,
        content=error_response.model_dump(),
        headers=_cors_headers(request),
    )


# Mount auth router
app.include_router(auth_router, prefix="/api/v1")

# Mount module management router (enable/upgrade/restart).
from app.core.plugins.router import apps_router  # noqa: E402
from app.core.plugins.router import router as modules_router  # noqa: E402

app.include_router(modules_router, prefix="/api/v1")
app.include_router(apps_router, prefix="/api/v1")

# Mount AI agents infrastructure router (approval queue, audit, agent CRUD).
from app.core.events.router import router as events_router  # noqa: E402

app.include_router(events_router, prefix="/api/v1")

from app.core.agents.router import router as agents_router  # noqa: E402

app.include_router(agents_router, prefix="/api/v1")

# Subject rights: export / erasure / the log of exercised rights.
from app.core.privacy.router import router as privacy_router  # noqa: E402

app.include_router(privacy_router, prefix="/api/v1")

# The operator's notices, as each clinic's members read them.
from app.core.announcements.router import router as announcements_router  # noqa: E402

app.include_router(announcements_router, prefix="/api/v1")

# What the control plane reads: usage and access per clinic (ADR 0049).
from app.core.ops.router import router as ops_router  # noqa: E402

app.include_router(ops_router, prefix="/api/v1")


@app.get("/health")
async def health_check() -> JSONResponse:
    """Liveness probe — process is up.

    Used by the proxy/orchestrator to decide whether the container should
    receive traffic. Must NOT depend on the DB: a transient DB blip should
    not pull the backend out of the load balancer (we used to do that and
    Cloudflare ended up serving "no available server" until someone redeployed
    by hand).
    """
    return JSONResponse(content={"status": "healthy", "version": "2.0.0"})


@app.get("/health/ready")
async def readiness_check(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    """Readiness probe — schema is reachable.

    Probes a core table so monitoring catches the case where the DB volume
    gets recreated under a running container (schema gone, every business
    endpoint 500s). Recovery from that state belongs in the entrypoint
    (`alembic upgrade heads`) plus an explicit container restart — not in
    the proxy healthcheck, since Docker's `restart: unless-stopped` does
    not auto-restart on healthcheck failure.
    """
    try:
        await db.execute(text("SELECT 1 FROM users LIMIT 1"))
    except Exception as exc:
        logger.error("Readiness check failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "unready", "version": "2.0.0", "error": str(exc)},
        )
    return JSONResponse(content={"status": "ready", "version": "2.0.0"})


@app.get("/api/v1")
async def api_root() -> dict:
    """API root endpoint."""
    return {
        "message": "Diente Azul API",
        "version": "2.0.0",
        "docs": "/docs" if settings.ENVIRONMENT == "development" else None,
    }
