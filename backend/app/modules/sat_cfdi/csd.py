"""Reading a CSD (certificado de sello digital) the SAT issued.

The ``.cer`` is an X.509 certificate in DER whose serial number spells
the 20-digit certificate number in ASCII and whose
``x500UniqueIdentifier`` carries ``RFC / CURP``. The ``.key`` is the
private key, PKCS#8 DER, encrypted with the holder's password.

Telling a CSD from an e.firma (FIEL), which has the same shape, is not
done here: the PAC refuses a FIEL when it is registered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID

from .models import RFC


class CsdError(ValueError):
    """Why a CSD cannot sign for the clinic. ``reason`` names the case."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CsdInfo:
    certificate_number: str
    rfc: str
    valid_from: datetime
    valid_until: datetime


def _public(key) -> bytes:
    return key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _certificate_number(certificate: x509.Certificate) -> str | None:
    digits = format(certificate.serial_number, "x")
    try:
        number = bytes.fromhex(digits.zfill(len(digits) + len(digits) % 2)).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return None
    return number if len(number) == 20 and number.isdigit() else None


def _rfc(certificate: x509.Certificate) -> str | None:
    found = certificate.subject.get_attributes_for_oid(NameOID.X500_UNIQUE_IDENTIFIER)
    if not found:
        return None
    rfc = str(found[0].value).split("/")[0].strip().upper()
    return rfc if RFC.match(rfc) else None


def read_csd(cer: bytes, key: bytes, password: str, *, now: datetime | None = None) -> CsdInfo:
    """What the CSD says, once it is shown to be usable today."""
    try:
        certificate = x509.load_der_x509_certificate(cer)
    except ValueError as exc:
        raise CsdError("unreadable", "El archivo .cer no es un certificado.") from exc

    number, rfc = _certificate_number(certificate), _rfc(certificate)
    if number is None or rfc is None:
        raise CsdError(
            "not_csd", "El certificado no es un CSD del SAT: le falta el número o el RFC."
        )

    try:
        private_key = serialization.load_der_private_key(key, password.encode())
    except (ValueError, TypeError) as exc:
        raise CsdError(
            "key_invalid", "La contraseña no abre el archivo .key, o no es una llave privada."
        ) from exc
    if _public(private_key.public_key()) != _public(certificate.public_key()):
        raise CsdError("key_mismatch", "El archivo .key no corresponde a este certificado.")

    now = now or datetime.now(UTC)
    valid_from, valid_until = certificate.not_valid_before_utc, certificate.not_valid_after_utc
    if not valid_from <= now <= valid_until:
        raise CsdError(
            "not_valid_now",
            f"El CSD solo es válido del {valid_from:%d/%m/%Y} al {valid_until:%d/%m/%Y}.",
        )
    return CsdInfo(
        certificate_number=number, rfc=rfc, valid_from=valid_from, valid_until=valid_until
    )
