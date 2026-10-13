"""HTTP endpoints for module management.

A subset of the CLI: everything read-only, plus the transitions that
cannot lose data. The heavy lifting happens at the next backend restart —
every mutating endpoint responds ``202 Accepted`` with a "restart
required" message and the list of modules that would be touched.

Routes are mounted at ``/api/v1/modules``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import (
    ClinicContext,
    get_clinic_context,
    require_permission,
)
from app.core.auth.permissions import has_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .apps import (
    AppStatus,
    integrated_modules,
    load_app_catalog,
    modules_disabled_by_app,
    modules_outside,
    required_apps,
    required_modules,
    statuses_on_disk,
)
from .service import ModuleOperationError, ModuleService
from .state import ModuleState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/modules", tags=["modules"])
apps_router = APIRouter(prefix="/apps", tags=["apps"])


@apps_router.get("")
async def list_apps(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
) -> ApiResponse[list[dict[str, Any]]]:
    """The App catalog: each App, the modules it groups and what they need.

    ``enabled`` is the caller's clinic's view: an App the deployment runs
    but that was not chosen for the clinic is not enabled for it.
    """
    on_disk = statuses_on_disk()
    chosen = ctx.clinic.apps
    offered = ctx.clinic.available_apps or []
    return ApiResponse(
        data=[
            {
                "name": app.name,
                "version": app.version,
                "enabled": app.enabled and (chosen is None or app.name in chosen),
                # Not the clinic's yet, and its administrator may switch it on.
                "available": (
                    app.enabled
                    and chosen is not None
                    and app.name not in chosen
                    and app.name in offered
                ),
                # What `apps.json` says now, when it differs from what is
                # running: the edit takes effect at the next restart.
                "pending_enabled": (
                    on_disk[app.name] is AppStatus.ENABLED
                    if app.name in on_disk and on_disk[app.name] is not app.status
                    else None
                ),
                # Switched off with this App, which it cannot run without.
                "held_back_by": app.held_back_by,
                "tier": app.tier.value,
                "modules": list(app.modules),
                "requires": required_modules(app),
                "integrates": integrated_modules(app),
                "apis": [{"name": api.name, "status": api.status.value} for api in app.apis],
            }
            for app in load_app_catalog()
        ]
    )


@apps_router.post("/{name}/enable")
async def enable_app(
    name: str,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
) -> ApiResponse[dict[str, Any]]:
    """Switch on, for the caller's clinic, an App it was offered.

    Takes effect at the next request: what a clinic has is checked per
    request (``get_clinic_context``), not decided at boot. The Apps it
    requires come on with it when they were offered too; it is refused
    when one of them was not. Nothing here switches an App off.
    """
    clinic = ctx.clinic
    catalog = {app.name: app for app in load_app_catalog()}
    chosen, offered = clinic.apps, clinic.available_apps or []
    if name not in catalog:
        raise HTTPException(status_code=404, detail=f"App not found: {name}")
    if chosen is None or name in chosen:
        return ApiResponse(data={"name": name, "enabled": True, "also_enabled": []})
    if name not in offered or not catalog[name].enabled:
        raise HTTPException(status_code=403, detail="This App is not available to this clinic")

    needed = [other for other in required_apps(catalog[name]) if other not in chosen]
    if missing := [other for other in needed if other not in offered]:
        raise HTTPException(
            status_code=409,
            detail=f"It needs Apps this clinic has not been offered: {', '.join(missing)}",
        )
    switched_on = {name, *needed}
    # New lists, not edits in place: that is what the ORM notices on JSONB.
    clinic.apps = [app for app in catalog if app in chosen or app in switched_on]
    clinic.available_apps = [app for app in offered if app not in switched_on]
    return ApiResponse(data={"name": name, "enabled": True, "also_enabled": needed})


# --- Read endpoints ------------------------------------------------------


@router.get("")
async def list_modules(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
) -> ApiResponse[list[dict[str, Any]]]:
    svc = ModuleService(db)
    infos = await svc.list_modules()
    return ApiResponse(data=[info.to_dict() for info in infos])


@router.get("/{name}")
async def get_module(
    name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
) -> ApiResponse[dict[str, Any]]:
    svc = ModuleService(db)
    info = await svc.get_info(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Module not found: {name}")
    return ApiResponse(data=info.to_dict())


@router.get("/-/status")
async def module_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
) -> ApiResponse[dict[str, Any]]:
    svc = ModuleService(db)
    return ApiResponse(data=await svc.status())


@router.get("/-/active")
async def active_modules(
    db: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
) -> ApiResponse[list[dict[str, Any]]]:
    """Modules that are running + nav items visible to the caller.

    Running means ``installed`` and not held back by a disabled App
    (ADR 0038) — the same set the boot sequence mounted.

    This is the frontend's source of truth for the sidebar. Every
    authenticated user may read it; navigation entries are filtered by
    the caller's role-based permissions so the response is already
    tailored to what the UI should render.
    """
    svc = ModuleService(db)
    active: list[dict[str, Any]] = []

    # Several modules may contribute the *same* destination on purpose:
    # payments, budget and billing each declare the "Finanzas" entry so
    # that it survives while any one of them is installed and goes with
    # the last. Collapsing them is this endpoint's job, not the client's
    # — a sidebar built by an older frontend against this response would
    # otherwise show the entry three times, which is exactly what one
    # did. De-duplication happens *after* the permission filter below,
    # so the entry still appears for a user who can see only one of the
    # contributing modules.
    seen_destinations: set[str] = set()
    # Held back for everyone by the deployment, or not among the Apps
    # chosen for this clinic: either way it is not there for the caller.
    held_back = modules_disabled_by_app() | modules_outside(ctx.clinic.apps)

    for info in await svc.list_modules():
        if info.state != ModuleState.INSTALLED or info.name in held_back:
            continue

        module = svc.discovered()
        manifest = next((m.get_manifest() for m in module if m.name == info.name), None)
        if manifest is None:
            continue

        nav = list(manifest.frontend.get("navigation") or [])
        filtered_nav = []
        for item in nav:
            if not _nav_visible(item, ctx.role):
                continue
            destination = item.get("to")
            if destination in seen_destinations:
                continue
            seen_destinations.add(destination)
            filtered_nav.append(item)

        active.append(
            {
                "name": manifest.name,
                "version": manifest.version,
                "category": manifest.category.value,
                "summary": manifest.summary,
                "navigation": filtered_nav,
                "permissions": [
                    f"{manifest.name}.{perm}"
                    for perm in next(
                        (m.get_permissions() for m in module if m.name == info.name),
                        [],
                    )
                ],
            }
        )

    return ApiResponse(data=active)


def _nav_visible(item: dict[str, Any], role: str) -> bool:
    perm = item.get("permission")
    if not perm:
        return True
    return has_permission(role, perm)


@router.get("/-/doctor")
async def module_doctor(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
) -> ApiResponse[dict[str, Any]]:
    svc = ModuleService(db)
    return ApiResponse(data=(await svc.doctor()).to_dict())


@router.get("/{name}/-/operations")
async def module_operations(
    name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("admin.clinic.read"))],
    limit: int = 20,
) -> ApiResponse[list[dict[str, Any]]]:
    """Return the most recent operation log rows for ``name``.

    ``limit`` is clamped to ``[1, 100]``. 404 if the module is unknown.
    """
    clamped = max(1, min(limit, 100))
    svc = ModuleService(db)
    try:
        entries = await svc.operation_log(name, limit=clamped)
    except ModuleOperationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=[entry.to_dict() for entry in entries])


# --- Mutating endpoints --------------------------------------------------


@router.post("/{name}/enable", status_code=status.HTTP_202_ACCEPTED)
async def enable_module(
    name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
) -> ApiResponse[dict[str, Any]]:
    """Enable ``name`` and the dependencies it needs.

    There is deliberately no ``disable`` (or ``uninstall``) over HTTP:
    turning an app off is an operator decision taken from the CLI, never
    a button (ADR 0035).
    """
    svc = ModuleService(db)
    try:
        scheduled = await svc.enable(name)
    except ModuleOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(
        data={"scheduled": scheduled, "requires_restart": bool(scheduled)},
        message="Restart required to apply.",
    )


@router.post("/{name}/upgrade", status_code=status.HTTP_202_ACCEPTED)
async def upgrade_module(
    name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
) -> ApiResponse[dict[str, Any]]:
    svc = ModuleService(db)
    try:
        changed = await svc.upgrade(name)
    except ModuleOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(
        data={"scheduled": [name] if changed else [], "requires_restart": changed},
        message=(
            "Restart required to apply."
            if changed
            else "Module is already at the declared version."
        ),
    )


@router.post("/-/restart", status_code=status.HTTP_202_ACCEPTED)
async def restart_backend(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(require_permission("admin.clinic.write"))],
) -> ApiResponse[dict[str, Any]]:
    """Send SIGTERM to container PID 1 so Docker respawns the process.

    The endpoint returns immediately; the actual shutdown runs in a
    background task with a small delay so the HTTP response flushes
    first. The container must have ``restart: unless-stopped`` set for
    the respawn to happen (see ``docker-compose.yml``).

    We target PID 1 rather than ``os.getpid()`` because under uvicorn's
    ``--reload`` (dev mode) the supervisor is PID 1 and the app worker
    is a child — killing only the worker leaves the supervisor idle
    without spawning a replacement. In production (no ``--reload``)
    PID 1 *is* the worker, so the same kill works identically.
    """
    background_tasks.add_task(_graceful_exit)
    return ApiResponse(
        data={"pid": os.getpid()},
        message="Restart scheduled.",
    )


async def _graceful_exit() -> None:
    await asyncio.sleep(0.5)
    logger.info("Sending SIGTERM to PID 1 (current pid=%s) for module restart", os.getpid())
    try:
        os.kill(1, signal.SIGTERM)
    except PermissionError:
        # Fallback: signal self. Works in prod where we are PID 1.
        logger.warning("No permission to signal PID 1; signalling self instead")
        os.kill(os.getpid(), signal.SIGTERM)
