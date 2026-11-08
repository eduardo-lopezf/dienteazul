"""SAT module API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import CFDI_USES, ENVIRONMENTS, RFC, TAX_REGIMES


class SatCfdiOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: UUID
    kind: str
    state: str
    uuid: str | None
    related_cfdi_id: UUID | None
    cancel_reason: str | None
    substitute_cfdi_id: UUID | None
    attempts: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class SatSettingsIn(BaseModel):
    tax_regime: str
    expedition_postal_code: str = Field(pattern=r"^\d{5}$")
    environment: str
    #: ``c_ClaveProdServ``: 8 digits.
    product_code: str | None = Field(default=None, pattern=r"^\d{8}$")
    #: ``c_ClaveUnidad``.
    unit_code: str = Field(default="E48", pattern=r"^[A-Z0-9]{2,3}$")
    stamp_delay_minutes: int = Field(default=30, ge=0, le=720)

    @field_validator("tax_regime")
    @classmethod
    def _tax_regime(cls, value: str) -> str:
        if value not in TAX_REGIMES:
            raise ValueError("Not a tax regime of the SAT's c_RegimenFiscal catalogue")
        return value

    @field_validator("environment")
    @classmethod
    def _environment(cls, value: str) -> str:
        if value not in ENVIRONMENTS:
            raise ValueError(f"Environment must be one of {', '.join(ENVIRONMENTS)}")
        return value


class SatCertificateOut(BaseModel):
    """A CSD as shown: never its key or password, not even encrypted."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    certificate_number: str
    rfc: str
    valid_from: datetime
    valid_until: datetime
    is_active: bool
    created_at: datetime
    #: The environments Facturama holds it in, to seal with.
    registered_in: list[str]
    #: Why the last attempt to register it did not go through.
    registration_error: str | None


class FacturamaAccountOut(BaseModel):
    """A clinic's Facturama account in one environment: never the password."""

    user: str | None
    has_password: bool


class FacturamaCredentialsIn(BaseModel):
    environment: str
    user: str = Field(min_length=1, max_length=120)
    #: Omitted keeps the stored one.
    password: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("environment")
    @classmethod
    def _environment(cls, value: str) -> str:
        if value not in ENVIRONMENTS:
            raise ValueError(f"Environment must be one of {', '.join(ENVIRONMENTS)}")
        return value


class SatSettingsOut(BaseModel):
    #: The clinic's own: ``Clinic.tax_id`` and ``Clinic.legal_name``.
    rfc: str | None
    legal_name: str | None
    tax_regime: str | None
    expedition_postal_code: str | None
    environment: str
    product_code: str | None
    unit_code: str
    stamp_delay_minutes: int
    #: The clinic's own Facturama account, per environment.
    facturama: dict[str, FacturamaAccountOut]
    certificate: SatCertificateOut | None
    #: Whether an invoice can be issued, and when not, why.
    ready: bool
    missing: str | None


class SatReceiverIn(BaseModel):
    tax_regime: str
    tax_zip_code: str = Field(pattern=r"^\d{5}$")
    cfdi_use: str = "D01"

    @field_validator("tax_regime")
    @classmethod
    def _tax_regime(cls, value: str) -> str:
        if value not in TAX_REGIMES:
            raise ValueError("Not a tax regime of the SAT's c_RegimenFiscal catalogue")
        return value

    @field_validator("cfdi_use")
    @classmethod
    def _cfdi_use(cls, value: str) -> str:
        if value not in CFDI_USES:
            raise ValueError("Not a use of the SAT's c_UsoCFDI catalogue")
        return value


class SatReceiverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rfc: str
    tax_regime: str
    tax_zip_code: str
    cfdi_use: str
    updated_at: datetime


def valid_rfc(rfc: str) -> str:
    """The RFC as kept — upper case — or ``ValueError``."""
    rfc = rfc.strip().upper()
    if not RFC.match(rfc):
        raise ValueError("Not an RFC")
    return rfc
