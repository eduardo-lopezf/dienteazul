"""Load stable SAT error codes from ``errors.json``."""

from __future__ import annotations

from typing import Final

from app.core.errors import AppError, ErrorDefinition, error_raiser, load_error_catalog

from .csd import CsdError
from .pac import PacError

ERROR_CATALOG: Final[dict[str, ErrorDefinition]] = load_error_catalog(__file__)

#: Raise one of this module's declared cases. See ``errors.json``.
sat_error = error_raiser(ERROR_CATALOG)

_CERTIFICATE_CODES: Final[dict[str, str]] = {
    "unreadable": "sat_cfdi.certificate.unreadable",
    "not_csd": "sat_cfdi.certificate.not_csd",
    "key_invalid": "sat_cfdi.certificate.key_invalid",
    "key_mismatch": "sat_cfdi.certificate.key_mismatch",
    "not_valid_now": "sat_cfdi.certificate.not_valid_now",
    "rfc_mismatch": "sat_cfdi.certificate.rfc_mismatch",
}


def certificate_error(error: CsdError) -> AppError:
    return sat_error(_CERTIFICATE_CODES[error.reason], detail=str(error))


def pac_error(error: PacError) -> AppError:
    code = "sat_cfdi.pac.unavailable" if error.transient else "sat_cfdi.certificate.pac_refused"
    return sat_error(code, detail=str(error))


def certificate_missing(detail: str) -> AppError:
    return sat_error("sat_cfdi.certificate.missing", detail=detail)


def rfc_invalid(rfc: str) -> AppError:
    return sat_error("sat_cfdi.receiver.rfc_invalid", detail=f"«{rfc}» no es un RFC.")
