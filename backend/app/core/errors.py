"""What failed, in terms the caller can act on and the operator can find.

A failure crosses three audiences, and each needs a different thing:

- **The person** needs to know whether it is theirs to fix, and to be
  able to quote the failure to whoever can look. They get the
  ``reference``: the ``request_id`` this request already carries into
  every log line and into the ``ServerError`` row the operator's panel
  reads (ADR 0049). One string ties the three together.
- **The interface** needs to know how to react — show a field error,
  send to login, offer a retry. It gets the ``category``.
- **Whoever debugs** needs to know which case this is out of the dozen a
  route can refuse for. They get the ``code``.

``code`` is dotted and stable: ``<module>.<resource>.<case>``. It is read
as it is, so there is no catalogue of numbers to keep in step with the
code — the shape Stripe and Google's APIs use, for the same reason. The
number a person reads out is the ``reference``, which already exists and
already points at the logs.

``AppError`` is an ``HTTPException`` on purpose: every route, dependency
and handler that already knows what to do with one keeps working, and
only the error handler looks for the extra fields. Raising a plain
``HTTPException`` stays valid — it is categorised from its status and
gets a reference, it just has no code.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final

from fastapi import HTTPException, status


class ErrorCategory(StrEnum):
    """The class of failure, which is what decides how a screen reacts."""

    #: The request was understood and is wrong. The person can fix it.
    VALIDATION = "validation"
    #: Not signed in, or signed in without the right to this.
    AUTH = "auth"
    #: Addressed something that is not there — or not theirs to see.
    NOT_FOUND = "not_found"
    #: Collides with the state of the thing: already exists, already closed.
    CONFLICT = "conflict"
    #: Allowed, but not this often or not this much.
    LIMIT = "limit"
    #: Something this depends on is off or unreachable. Not the caller's doing.
    DEPENDENCY = "dependency"
    #: Nobody expected it. The only category that means "we have a defect".
    INTERNAL = "internal"


_BY_STATUS: Final[dict[int, ErrorCategory]] = {
    status.HTTP_400_BAD_REQUEST: ErrorCategory.VALIDATION,
    status.HTTP_401_UNAUTHORIZED: ErrorCategory.AUTH,
    status.HTTP_403_FORBIDDEN: ErrorCategory.AUTH,
    status.HTTP_404_NOT_FOUND: ErrorCategory.NOT_FOUND,
    status.HTTP_409_CONFLICT: ErrorCategory.CONFLICT,
    status.HTTP_422_UNPROCESSABLE_ENTITY: ErrorCategory.VALIDATION,
    status.HTTP_429_TOO_MANY_REQUESTS: ErrorCategory.LIMIT,
    status.HTTP_503_SERVICE_UNAVAILABLE: ErrorCategory.DEPENDENCY,
}

#: What an unhandled exception is reported as. The one code a caller
#: should never see twice without somebody looking at it.
UNHANDLED_CODE: Final[str] = "internal.unhandled"


def category_for_status(status_code: int) -> ErrorCategory:
    """The category a bare status belongs to.

    Anything 5xx is ours; anything else unmapped is treated as the
    caller's to fix, which is the safer half to be wrong about: it says
    "look at what you sent" rather than "a defect, wait".
    """
    if status_code in _BY_STATUS:
        return _BY_STATUS[status_code]
    return ErrorCategory.INTERNAL if status_code >= 500 else ErrorCategory.VALIDATION


class AppError(HTTPException):
    """An HTTP failure that says which case it is.

    ``code`` names the case; ``category`` defaults to whatever the status
    means, and is only worth passing when the status is coarser than the
    cause — a 400 that is really a missing dependency, say.
    """

    def __init__(
        self,
        code: str,
        *,
        status_code: int,
        detail: str,
        category: ErrorCategory | None = None,
        headers: dict[str, str] | None = None,
        fields: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.category = category or category_for_status(status_code)
        #: Per-field messages, for a form that can point at the offender.
        self.fields = fields or {}


def not_found(code: str, detail: str) -> AppError:
    return AppError(code, status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def conflict(code: str, detail: str) -> AppError:
    return AppError(code, status_code=status.HTTP_409_CONFLICT, detail=detail)


def invalid(code: str, detail: str, fields: dict[str, Any] | None = None) -> AppError:
    return AppError(
        code,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
        fields=fields,
    )


def unavailable(code: str, detail: str) -> AppError:
    """Something this needs is switched off (ADR 0038) or unreachable."""
    return AppError(code, status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
