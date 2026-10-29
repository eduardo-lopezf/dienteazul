"""Where the rate limiter counts, and how many connections a process holds.

Both are per process by default, which is right for one backend and wrong
for several: each would allow the full limit, and each would open a full
pool. They are settings so that a deployment with several backends can
say otherwise — and these tests pin that a deployment which says nothing
keeps exactly what it had.
"""

import re
from pathlib import Path
from uuid import uuid4

import pytest
from limits.storage import MemoryStorage
from starlette.requests import Request

from app.config import Settings
from app.core.auth.router import _bearer_rate_key, _login_rate_key, build_limiter
from app.core.auth.service import create_access_token

# Source-level rules and pure functions: no DB, no app. CI runs these
# before the suite so a limiter keyed on the socket peer fails in seconds.
pytestmark = pytest.mark.contract


def test_one_backend_keeps_what_it_had() -> None:
    fields = Settings.model_fields

    assert fields["RATE_LIMIT_STORAGE_URI"].default == ""
    assert fields["DB_POOL_SIZE"].default == 10
    assert fields["DB_MAX_OVERFLOW"].default == 20


def test_without_a_store_the_limiter_counts_in_memory() -> None:
    limiter = build_limiter("", enabled=True)

    assert isinstance(limiter._storage, MemoryStorage)
    # Nothing to fall back from.
    assert limiter._in_memory_fallback_enabled is False


def test_with_a_store_the_limiter_survives_losing_it() -> None:
    """A shared store is one more thing that can be down, and the limiter
    sits in front of the login. ``memory://`` stands in for it here: what
    is pinned is that naming a store turns the fallback on."""
    limiter = build_limiter("memory://", enabled=True)

    assert limiter._storage_uri == "memory://"
    assert limiter._in_memory_fallback_enabled is True


def test_session_endpoints_are_limited_per_user_not_per_socket() -> None:
    """A session limiter keyed on the peer counts the whole deployment.

    Every browser request arrives through the BFF (ADR 0052), so
    ``get_remote_address`` is one bucket for everybody:
    ``/auth/activity`` was 30 signals a minute between *all* users — and
    running out is what freezes a session family's clock and throws
    somebody out mid-task — while ``/auth/login`` was five sign-ins a
    minute for an entire clinic. ``_refresh_rate_key`` fixed that for
    ``/auth/refresh`` alone; this is the rule for the rest (ADR 0062).

    Read off the source rather than the app: the limiter is disabled
    outside production, so nothing at runtime would show the key back.
    """
    source = (Path(__file__).resolve().parents[1] / "app/core/auth/router.py").read_text()

    # Every endpoint that can end, extend or open a session.
    for path in ("/refresh", "/logout", "/activity", "/password", "/login"):
        decorators = re.findall(rf'@router\.post\("{re.escape(path)}".*?\nasync def', source, re.S)
        assert decorators, f"{path} is no longer a POST on this router"
        limits = [line for line in decorators[0].splitlines() if "@limiter.limit(" in line]
        assert limits, f"{path} is not rate limited"
        for limit in limits:
            # One looser per-host bucket is allowed alongside a keyed
            # one — on login it is what stops a single machine working
            # through many accounts.
            if "key_func=" in limit or len(limits) > 1:
                continue
            raise AssertionError(f"{path} is limited per socket peer: {limit.strip()}")


def _request(method: str, path: str, *, headers: dict[str, str], body: bytes) -> Request:
    """A request the key functions can read, without a running app.

    Worth building by hand: the limiter is disabled outside production
    (``_limiter_enabled``), so these functions never run in dev or in the
    rest of the suite — production would be their first execution.
    """
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("203.0.113.7", 1234),
        "query_string": b"",
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


@pytest.mark.asyncio
async def test_login_is_counted_per_account_and_falls_back_to_the_caller() -> None:
    form = b"username=Admin%40Demo.Clinic&password=whatever"
    request = _request(
        "POST",
        "/api/v1/auth/login",
        headers={"content-type": "application/x-www-form-urlencoded"},
        body=form,
    )

    # Case-folded, so capitalising the address does not buy a fresh bucket.
    assert await _login_rate_key(request) == "login:admin@demo.clinic"

    # And the form the key is read from is still there for the endpoint.
    assert (await request.form())["username"] == "Admin%40Demo.Clinic".replace("%40", "@")

    nameless = _request("POST", "/api/v1/auth/login", headers={}, body=b"")
    assert await _login_rate_key(nameless) == "203.0.113.7"


def test_an_authenticated_endpoint_is_counted_per_user() -> None:
    user_id = uuid4()
    token = create_access_token(user_id)
    request = _request(
        "POST",
        "/api/v1/auth/activity",
        headers={"authorization": f"Bearer {token}"},
        body=b"",
    )

    assert _bearer_rate_key(request) == f"user:{user_id}"

    # A token nobody signed must not become somebody's bucket.
    forged = _request(
        "POST", "/api/v1/auth/activity", headers={"authorization": "Bearer nope"}, body=b""
    )
    assert _bearer_rate_key(forged) == "203.0.113.7"
