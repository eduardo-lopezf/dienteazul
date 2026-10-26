"""Load stable whatsapp_kapso error codes from ``errors.json``."""

from __future__ import annotations

from typing import Final

from app.core.errors import (
    AppError,
    ErrorDefinition,
    error_raiser,
    load_error_catalog,
)

from .client import KapsoError

ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = load_error_catalog(__file__)

#: Raise one of this module's declared cases. See ``errors.json``.
whatsapp_kapso_error = error_raiser(ERROR_CATALOG)


def template_sync_error(error: ValueError | KapsoError) -> AppError:
    """Translate settings and provider failures without exposing provider details."""
    if isinstance(error, KapsoError):
        return whatsapp_kapso_error("whatsapp_kapso.provider.unavailable")
    return whatsapp_kapso_error(
        "whatsapp_kapso.settings.not_configured",
        detail=str(error),
    )
