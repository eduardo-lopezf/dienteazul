"""Load stable Calendar feed error codes from ``errors.json``."""

from __future__ import annotations

from typing import Final

from app.core.errors import ErrorDefinition, error_raiser, load_error_catalog

ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = load_error_catalog(__file__)

#: Raise one of this module's declared cases. See ``errors.json``.
calendar_feed_error = error_raiser(ERROR_CATALOG)
