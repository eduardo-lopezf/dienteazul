"""SAT (CFDI 4.0) module database models."""

import re
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.core.privacy import DataClass, PiiKind, pii
from app.database import Base, TimestampMixin

#: Persona moral (3 letters) or física (4), date of birth or incorporation,
#: homoclave. ``XAXX010101000`` (general public) matches too.
RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")

#: ``TipoDeComprobante``: ingreso (invoice), egreso (credit note), pago
#: (payment complement).
CFDI_KINDS = ("I", "E", "P")

#: ``pending`` waits for the stamping job; ``cancel_requested`` for the
#: SAT's answer (ADR 0067).
CFDI_STATES = ("pending", "stamped", "rejected", "cancel_requested", "cancelled")

#: The SAT's cancellation reasons (``Motivo``). ``01`` needs a substitute.
CANCEL_REASONS = ("01", "02", "03", "04")

#: ``c_RegimenFiscal`` — the tax regimes the SAT's catalogue lists.
TAX_REGIMES = (
    "601", "603", "605", "606", "607", "608", "610", "611", "612", "614",
    "615", "616", "620", "621", "622", "623", "624", "625", "626",
)  # fmt: skip

#: ``sandbox`` stamps against the PAC's test service; nothing reaches the SAT.
ENVIRONMENTS = ("sandbox", "production")

#: ``c_UsoCFDI``. ``D01`` is "Honorarios médicos, dentales y gastos
#: hospitalarios", a personal deduction; ``S01`` is "Sin efectos fiscales".
CFDI_USES = (
    "G01", "G02", "G03", "I01", "I02", "I03", "I04", "I05", "I06", "I07", "I08",
    "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10",
    "S01", "CP01", "CN01",
)  # fmt: skip

#: The SAT's generic RFC for the general public, and what goes with it.
PUBLIC_RFC = "XAXX010101000"
PUBLIC_REGIME = "616"
PUBLIC_CFDI_USE = "S01"


class SatSettings(Base, TimestampMixin):
    """What the SAT needs of a clinic as issuer, besides its RFC and name.

    The RFC and the legal name are the clinic's own (``Clinic.tax_id``,
    ``Clinic.legal_name``), read from there and never copied.
    """

    __tablename__ = "sat_settings"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), unique=True, index=True)
    #: ``RegimenFiscal`` of the issuer (``601``, ``612``, ``626`` RESICO…).
    tax_regime: Mapped[str | None] = mapped_column(String(3), default=None)
    #: ``LugarExpedicion``: the postal code the CFDI is issued from.
    expedition_postal_code: Mapped[str | None] = mapped_column(String(5), default=None)
    environment: Mapped[str] = mapped_column(String(10), default="sandbox")
    #: ``ClaveProdServ`` for every line — the clinic chooses it from the
    #: SAT's ``c_ClaveProdServ``; there is no default.
    product_code: Mapped[str | None] = mapped_column(String(8), default=None)
    #: ``ClaveUnidad``; ``E48`` is "Unidad de servicio".
    unit_code: Mapped[str] = mapped_column(String(3), default="E48")
    #: How long a CFDI waits before it is stamped, so a payment recorded
    #: right after issuing makes it ``PUE``. The SAT allows 24 hours.
    stamp_delay_minutes: Mapped[int] = mapped_column(Integer, default=30)

    # The clinic's own Facturama account, per environment: each tenant has
    # its own, so it never comes from the deployment's environment. The
    # password is encrypted with SECRET_KEY and never shown back.
    facturama_sandbox_user: Mapped[str | None] = mapped_column(String(120), default=None)
    facturama_sandbox_password_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    facturama_production_user: Mapped[str | None] = mapped_column(String(120), default=None)
    facturama_production_password_encrypted: Mapped[str | None] = mapped_column(Text, default=None)

    def facturama_user(self, environment: str) -> str | None:
        return getattr(self, f"facturama_{environment}_user")

    def facturama_password(self, environment: str) -> str | None:
        """Decrypted; ``None`` when there is none or it cannot be read."""
        from app.core.email.encryption import decrypt_password

        token = getattr(self, f"facturama_{environment}_password_encrypted")
        return decrypt_password(token) if token else None


class SatReceiver(Base, TimestampMixin):
    """What the SAT needs of a receiver besides the name: kept by RFC.

    The regime and the fiscal postal code are the taxpayer's, so they are
    asked once per RFC, whatever patient the invoice is for. The name
    comes from the invoice (``billing_name``).
    """

    __tablename__ = "sat_receivers"
    __table_args__ = (UniqueConstraint("clinic_id", "rfc", name="uq_sat_receivers_rfc"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    rfc: Mapped[str] = mapped_column(
        String(13), info=pii(PiiKind.NATIONAL_ID, data_class=DataClass.FINANCIAL)
    )
    tax_regime: Mapped[str] = mapped_column(String(3))
    #: ``DomicilioFiscalReceptor``: the postal code on their tax certificate.
    tax_zip_code: Mapped[str] = mapped_column(String(5))
    cfdi_use: Mapped[str] = mapped_column(String(4), default="D01")


class SatCertificate(Base, TimestampMixin):
    """A clinic's CSD (certificado de sello digital).

    The certificate (``.cer``) is public and kept as it came; the private
    key (``.key``) and its password are encrypted with ``SECRET_KEY``
    (``app.core.email.encryption``). One active per clinic; replaced ones
    are kept, inactive.
    """

    __tablename__ = "sat_certificates"
    __table_args__ = (
        Index(
            "uq_sat_certificates_one_active",
            "clinic_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    cer: Mapped[bytes] = mapped_column(LargeBinary)
    key_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    password_encrypted: Mapped[str] = mapped_column(Text)

    #: ``NoCertificado``: 20 digits, from the certificate's serial number.
    certificate_number: Mapped[str] = mapped_column(String(20))
    #: The holder's RFC — a person's own when the clinic is a persona física.
    rfc: Mapped[str] = mapped_column(
        String(13), info=pii(PiiKind.NATIONAL_ID, data_class=DataClass.FINANCIAL)
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), default=None)

    #: When Facturama got it, to seal with, in each environment — separate
    #: accounts, so registering in one says nothing of the other.
    registered_sandbox_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    registered_production_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    #: Why the last attempt to register it did not go through.
    registration_error: Mapped[str | None] = mapped_column(Text, default=None)

    def is_registered_in(self, environment: str) -> bool:
        return getattr(self, f"registered_{environment}_at") is not None

    @property
    def registered_in(self) -> list[str]:
        return [e for e in ENVIRONMENTS if self.is_registered_in(e)]


class SatCfdi(Base, TimestampMixin):
    """One CFDI for one billing document, from queued to stamped or cancelled.

    Written by the hook in the same transaction as the billing change; a
    scheduled job sends it to the PAC after commit (ADR 0067). It holds no
    personal data of its own: the receiver is the invoice's.
    """

    __tablename__ = "sat_cfdi"
    __table_args__ = (
        CheckConstraint("kind IN ('I', 'E', 'P')", name="ck_sat_cfdi_kind"),
        CheckConstraint(
            "state IN ('pending', 'stamped', 'rejected', 'cancel_requested', 'cancelled')",
            name="ck_sat_cfdi_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    # FK allowed: `billing` is in `manifest.depends`.
    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    kind: Mapped[str] = mapped_column(String(1))
    state: Mapped[str] = mapped_column(String(20), default="pending")
    #: The ingreso an egreso or a payment complement relates to.
    related_cfdi_id: Mapped[UUID | None] = mapped_column(ForeignKey("sat_cfdi.id"), default=None)
    #: The SAT's folio fiscal, once stamped.
    uuid: Mapped[str | None] = mapped_column(String(36), unique=True, default=None)

    cancel_reason: Mapped[str | None] = mapped_column(String(2), default=None)
    substitute_cfdi_id: Mapped[UUID | None] = mapped_column(ForeignKey("sat_cfdi.id"), default=None)
    #: Who asked; ``mark_cancelled`` records them when the SAT confirms.
    cancel_requested_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), default=None)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    #: Not before this, after a failed attempt.
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    #: ``Fecha`` as sent, fixed on the first attempt: Facturama tells an
    #: operation apart by ``Folio`` and ``Date``, so a retry repeats both.
    cfdi_date: Mapped[str | None] = mapped_column(String(19), default=None)
    #: ``MetodoPago`` (``PUE`` / ``PPD``) and ``FormaPago``, decided when stamped.
    payment_method: Mapped[str | None] = mapped_column(String(3), default=None)
    payment_form: Mapped[str | None] = mapped_column(String(2), default=None)

    #: Facturama's id for it, to download or cancel it.
    pac_id: Mapped[str | None] = mapped_column(String(64), default=None)
    #: The stamped XML, as the SAT has it.
    xml: Mapped[str | None] = mapped_column(Text, default=None)
    stamped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
