"""Core schemas for standardized API responses."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Wrapper for individual item responses."""

    data: T
    message: str | None = None


class PaginatedApiResponse(BaseModel, Generic[T]):
    """Wrapper for paginated list responses."""

    data: list[T]
    total: int
    page: int
    page_size: int
    message: str | None = None


class ErrorResponse(BaseModel):
    """Standard error response.

    ``message`` and ``errors`` are what to show. The other three are what
    makes a failure findable afterwards (``app/core/errors.py``):

    - ``category`` — the class of failure, which the interface branches on.
    - ``code`` — which case this is, as ``<module>.<resource>.<case>``.
      Absent when nothing claimed the failure, e.g. a bare
      ``HTTPException``.
    - ``reference`` — this request's id. The same string prefixes every
      log line it produced and names its line in the server-error log, so a
      person who reads it out leads the operator straight to the cause.
    """

    data: None = None
    message: str
    errors: list[str] = []
    category: str | None = None
    code: str | None = None
    reference: str | None = None
    #: Per-field messages, when the failure is a form's to fix.
    fields: dict[str, Any] = {}
