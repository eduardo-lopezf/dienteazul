"""Test CSDs shaped like the SAT's, and a clinic ready to issue in Mexico.

A real CSD is an X.509 certificate (``.cer``, DER) whose serial number
spells its 20-digit certificate number in ASCII and whose
``x500UniqueIdentifier`` carries the holder's RFC; the private key
(``.key``) is PKCS#8 DER encrypted with the holder's password. These are
self-signed with the same shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.sat_cfdi import pac

#: The SAT's own test issuer RFC.
ISSUER_RFC = "EKU9003173C9"
CERTIFICATE_NUMBER = "30001000000500003416"
PASSWORD = "12345678a"


@dataclass
class Csd:
    cer: bytes
    key: bytes
    password: str


def make_csd(
    *,
    rfc: str = ISSUER_RFC,
    number: str = CERTIFICATE_NUMBER,
    password: str = PASSWORD,
    not_before: datetime | None = None,
    not_after: datetime | None = None,
    with_rfc: bool = True,
) -> Csd:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attributes = [x509.NameAttribute(NameOID.COMMON_NAME, "ESCUELA KEMPER URGATE")]
    if with_rfc:
        attributes.append(x509.NameAttribute(NameOID.X500_UNIQUE_IDENTIFIER, f"{rfc} / "))
    name = x509.Name(attributes)
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(int(number.encode("ascii").hex(), 16))
        .not_valid_before(not_before or now - timedelta(days=1))
        .not_valid_after(not_after or now + timedelta(days=365 * 4))
        .sign(key, hashes.SHA256())
    )
    return Csd(
        cer=certificate.public_bytes(serialization.Encoding.DER),
        key=key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(password.encode()),
        ),
        password=password,
    )


class FakePac:
    """Stands in for Facturama: records what it was asked, answers as told."""

    def __init__(self) -> None:
        self.registered: list[dict] = []
        self.stamped: list[dict] = []
        self.uuid = "FE3C73D5-7881-49E0-80A3-E6C7E2EECE40"
        self.fail: pac.PacError | None = None

    async def register_csd(
        self, rfc: str, cer: bytes, key: bytes, password: str, *, replace: bool
    ) -> None:
        if self.fail:
            raise self.fail
        self.registered.append({"rfc": rfc, "replace": replace, "password": password})

    async def stamp_cfdi(self, payload: dict) -> pac.StampResult:
        if self.fail:
            raise self.fail
        self.stamped.append(payload)
        return pac.StampResult(pac_id="FAKE-1", uuid=self.uuid, xml="<cfdi:Comprobante/>")


@pytest.fixture(autouse=True)
def fake_pac(monkeypatch) -> FakePac:
    """No test of this module reaches Facturama."""
    fake = FakePac()
    environments: list[str] = []

    def client_for(settings) -> FakePac:
        environments.append(settings.environment)
        return fake

    monkeypatch.setattr(pac, "client_for", client_for)
    fake.environments = environments
    return fake


@pytest_asyncio.fixture
async def mexican_clinic(db_session: AsyncSession, test_clinic: Clinic) -> Clinic:
    """The test clinic, in Mexico, with the SAT's test RFC and the SAT
    module switched on (an optional module of Budgets & payments, ADR 0066)."""
    test_clinic.settings = {**(test_clinic.settings or {}), "country": "MX"}
    test_clinic.modules = ["sat_cfdi"]
    test_clinic.tax_id = ISSUER_RFC
    test_clinic.legal_name = "ESCUELA KEMPER URGATE"
    await db_session.commit()
    return test_clinic


async def set_credentials(client, headers: dict, environment: str = "sandbox") -> None:
    """The clinic's own Facturama account for an environment."""
    response = await client.put(
        "/api/v1/sat_cfdi/facturama-credentials",
        json={"environment": environment, "user": "clinica-demo", "password": "secreta"},
        headers=headers,
    )
    assert response.status_code == 200, response.text


async def configure_issuer(client, headers: dict, csd: Csd | None = None) -> None:
    """Fill the SAT settings, the Facturama account and upload a CSD, through the API."""
    settings = await client.put(
        "/api/v1/sat_cfdi/settings",
        json={
            "tax_regime": "601",
            "expedition_postal_code": "42501",
            "environment": "sandbox",
            "product_code": "85121800",
            "unit_code": "E48",
        },
        headers=headers,
    )
    assert settings.status_code == 200, settings.text
    await set_credentials(client, headers)
    csd = csd or make_csd()
    uploaded = await client.post(
        "/api/v1/sat_cfdi/certificate",
        files={
            "cer": ("csd.cer", csd.cer, "application/octet-stream"),
            "key": ("csd.key", csd.key, "application/octet-stream"),
        },
        data={"password": csd.password},
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text
