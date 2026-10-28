"""The subscription's own endpoints, for the user who owns it.

Mounted at ``/api/v1/calendar_feed/*``. The public document is in
``public_router.py``: it carries no session at all.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .errors import calendar_feed_error
from .integrations import agenda_available
from .models import CalendarFeed
from .schemas import CalendarFeedResponse
from .service import CalendarFeedService

router = APIRouter()

#: Where the public document lives, as the module is mounted.
FEED_PATH = "/api/v1/calendar_feed/calendar/{token}.ics"


async def _present(
    db: AsyncSession, ctx: ClinicContext, feed: CalendarFeed
) -> CalendarFeedResponse:
    professional_id = await CalendarFeedService.scope(db, ctx.clinic_id, ctx.user_id)
    return CalendarFeedResponse(
        token=feed.token,
        path=FEED_PATH.format(token=feed.token),
        scope="own" if professional_id else "clinic",
        last_access_at=feed.last_access_at,
        created_at=feed.created_at,
    )


@router.get("/subscription", response_model=ApiResponse[CalendarFeedResponse | None])
async def get_subscription(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("calendar_feed.subscription.manage"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CalendarFeedResponse | None]:
    """The caller's own subscription, or ``null`` when they have none.

    Reading never creates one: a URL that carries patient names out of
    the clinic is something the user asks for.
    """
    feed = await CalendarFeedService.get(db, ctx.clinic_id, ctx.user_id)
    if feed is None:
        return ApiResponse(data=None)
    return ApiResponse(data=await _present(db, ctx, feed))


@router.post(
    "/subscription",
    response_model=ApiResponse[CalendarFeedResponse],
    status_code=status.HTTP_201_CREATED,
)
async def issue_subscription(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("calendar_feed.subscription.manage"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CalendarFeedResponse]:
    """Create the subscription, or rotate the token of an existing one.

    Rotating kills the URLs already pasted elsewhere — that is what a
    user who shared theirs by mistake needs.
    """
    if not agenda_available():
        raise calendar_feed_error("calendar_feed.agenda.unavailable")
    feed = await CalendarFeedService.issue(db, ctx.clinic_id, ctx.user_id)
    return ApiResponse(data=await _present(db, ctx, feed))


@router.delete("/subscription", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_subscription(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("calendar_feed.subscription.manage"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Stop answering on this user's URL."""
    if not await CalendarFeedService.revoke(db, ctx.clinic_id, ctx.user_id):
        raise calendar_feed_error("calendar_feed.not_found")
