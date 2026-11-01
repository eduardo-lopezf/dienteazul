"""What the browser could not get an answer to, kept for the operator.

A request that never comes back leaves nothing on the server to look at.
The browser is the only witness: it gave up after its own budget, told
the user the server took too long, and that was the end of it — the
control panel's error console showed an afternoon with no failures in it
while a user was being thrown out of their session.

So the browser reports it, and the report lands in the same place as
everything else the operator reads (``GET /api/v1/ops/errors``, ADR
0060). Its companion is ``slow_request_middleware`` in ``app.main``,
which records the other half: the requests that *did* answer, far too
late. Between them, "slow" and "never came back" are both visible.

**Nothing the caller writes is kept.** The report is four bounded
fields — which route, which method, how long it waited, which of the two
cases — and the line's message is composed here from them. A browser
cannot put a patient's name into the operator's console through this,
even by accident, and there is no free-text field to try it with.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth.dependencies import get_current_user
from app.core.auth.models import User
from app.core.auth.router import bearer_rate_key, limiter
from app.core.server_errors import CLIENT_TIMEOUT_TYPE, record_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/client-errors", tags=["client-errors"])

#: What the recorded line is given as its status. The server sent none —
#: that is the whole report — so these name which way it stayed silent:
#: nothing arrived in time, or the connection itself did not hold.
_STATUS = {
    "timeout": status.HTTP_504_GATEWAY_TIMEOUT,
    "network": status.HTTP_503_SERVICE_UNAVAILABLE,
}


class ClientFailureReport(BaseModel):
    """One request the browser never got an answer to."""

    model_config = ConfigDict(extra="forbid")

    #: The route it was asking for. Trimmed of its query string by the
    #: caller; trimmed again here, because what a query string carries is
    #: usually somebody's identifier.
    path: str = Field(min_length=1, max_length=300)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    #: How long the browser waited before giving up. Bounded so the line
    #: cannot claim a day.
    waited_ms: int = Field(ge=0, le=600_000)
    kind: Literal["timeout", "network"]


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute", key_func=bearer_rate_key)
async def report_client_failure(
    request: Request,
    report: ClientFailureReport,
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Record a request the browser gave up on.

    Signed in and capped per user: the console is an operator's, and a
    page caught in a retry loop must not be able to bury the real
    failures under its own.
    """
    path = report.path.split("?", 1)[0]
    record_event(
        method=report.method,
        path=path,
        status_code=_STATUS[report.kind],
        error_type=CLIENT_TIMEOUT_TYPE,
        message=(
            f"the browser gave up after {report.waited_ms / 1000:.1f}s"
            if report.kind == "timeout"
            else f"the connection did not hold, after {report.waited_ms / 1000:.1f}s"
        ),
        # This report's own id: the request it is about produced none,
        # having never been answered. It still ties the line to the log
        # lines of the report itself.
        request_id=getattr(request.state, "request_id", None),
        clinic_id=getattr(request.state, "clinic_id", None),
        user_id=str(current_user.id),
    )
