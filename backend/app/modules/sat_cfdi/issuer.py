"""The clinic as issuer: its SAT settings and its CSD. Every query filters by clinic."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.email.encryption import (
    decrypt_bytes,
    decrypt_password,
    encrypt_bytes,
    encrypt_password,
)

from . import pac
from .csd import CsdError, read_csd
from .models import RFC, SatCertificate, SatSettings

_ENVIRONMENT_NAMES = {"sandbox": "pruebas", "production": "producción"}


class CertificateMissingError(LookupError):
    """There is no active CSD to do it with."""


class SatIssuerService:
    @staticmethod
    async def get_settings(db: AsyncSession, clinic_id: UUID) -> SatSettings | None:
        result = await db.execute(select(SatSettings).where(SatSettings.clinic_id == clinic_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def save_settings(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        tax_regime: str,
        expedition_postal_code: str,
        environment: str,
        product_code: str | None = None,
        unit_code: str = "E48",
        stamp_delay_minutes: int = 30,
    ) -> SatSettings:
        settings = await SatIssuerService.get_settings(db, clinic_id)
        if settings is None:
            settings = SatSettings(clinic_id=clinic_id)
            db.add(settings)
        settings.tax_regime = tax_regime
        settings.expedition_postal_code = expedition_postal_code
        settings.environment = environment
        settings.product_code = product_code
        settings.unit_code = unit_code
        settings.stamp_delay_minutes = stamp_delay_minutes
        await db.flush()
        return settings

    @staticmethod
    async def save_credentials(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        environment: str,
        user: str,
        password: str | None,
    ) -> SatSettings:
        """The clinic's Facturama account for one environment. ``password``
        ``None`` keeps the stored one."""
        settings = await SatIssuerService.get_settings(db, clinic_id)
        if settings is None:
            settings = SatSettings(clinic_id=clinic_id, environment="sandbox", unit_code="E48")
            db.add(settings)
        setattr(settings, f"facturama_{environment}_user", user.strip())
        if password is not None:
            setattr(
                settings, f"facturama_{environment}_password_encrypted", encrypt_password(password)
            )
        await db.flush()
        return settings

    @staticmethod
    async def active_certificate(db: AsyncSession, clinic_id: UUID) -> SatCertificate | None:
        result = await db.execute(
            select(SatCertificate).where(
                SatCertificate.clinic_id == clinic_id, SatCertificate.is_active.is_(True)
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _registered_before(db: AsyncSession, clinic_id: UUID, environment: str) -> bool:
        """Whether Facturama already holds a CSD of this clinic there — then a
        new one replaces it (``PUT``) instead of registering it (``POST``)."""
        column = getattr(SatCertificate, f"registered_{environment}_at")
        result = await db.execute(
            select(SatCertificate.id)
            .where(SatCertificate.clinic_id == clinic_id, column.is_not(None))
            .limit(1)
        )
        return result.first() is not None

    @staticmethod
    async def upload_certificate(
        db: AsyncSession,
        clinic: Clinic,
        *,
        cer: bytes,
        key: bytes,
        password: str,
        uploaded_by: UUID,
    ) -> SatCertificate:
        """Store a CSD the clinic can sign with; it replaces the active one.

        It is registered with Facturama first, in the clinic's environment.
        Refused there, it is not stored (``PacError`` propagates); with
        Facturama not answering it is stored unregistered, to retry with
        :meth:`register_active`.
        """
        info = read_csd(cer, key, password)
        if info.rfc != (clinic.tax_id or "").strip().upper():
            raise CsdError(
                "rfc_mismatch",
                f"El CSD es del RFC {info.rfc}, no del de la clínica ({clinic.tax_id}).",
            )

        settings = await SatIssuerService.get_settings(db, clinic.id)
        environment = settings.environment if settings else "sandbox"
        replace = await SatIssuerService._registered_before(db, clinic.id, environment)
        registered_at, registration_error = None, None
        try:
            await pac.client_for(settings).register_csd(
                info.rfc, cer, key, password, replace=replace
            )
            registered_at = datetime.now(UTC)
        except pac.PacError as exc:
            if not exc.transient:
                raise
            registration_error = str(exc)

        # Before the insert: the partial unique index allows one active.
        await db.execute(
            update(SatCertificate)
            .where(SatCertificate.clinic_id == clinic.id, SatCertificate.is_active.is_(True))
            .values(is_active=False)
        )
        certificate = SatCertificate(
            clinic_id=clinic.id,
            cer=cer,
            key_encrypted=encrypt_bytes(key),
            password_encrypted=encrypt_password(password),
            certificate_number=info.certificate_number,
            rfc=info.rfc,
            valid_from=info.valid_from,
            valid_until=info.valid_until,
            is_active=True,
            uploaded_by=uploaded_by,
            registration_error=registration_error,
        )
        setattr(certificate, f"registered_{environment}_at", registered_at)
        db.add(certificate)
        await db.flush()
        return certificate

    @staticmethod
    async def register_active(db: AsyncSession, clinic_id: UUID) -> SatCertificate:
        """Register the active CSD with Facturama in the clinic's environment."""
        certificate = await SatIssuerService.active_certificate(db, clinic_id)
        if certificate is None:
            raise CertificateMissingError("La clínica no tiene CSD que registrar.")
        key = decrypt_bytes(certificate.key_encrypted)
        password = decrypt_password(certificate.password_encrypted)
        if key is None or password is None:
            raise CsdError(
                "key_invalid",
                "La llave del CSD ya no se puede descifrar (¿cambió SECRET_KEY?). Súbelo de nuevo.",
            )

        settings = await SatIssuerService.get_settings(db, clinic_id)
        environment = settings.environment if settings else "sandbox"
        replace = await SatIssuerService._registered_before(db, clinic_id, environment)
        try:
            await pac.client_for(settings).register_csd(
                certificate.rfc, certificate.cer, key, password, replace=replace
            )
        except pac.PacError as exc:
            certificate.registration_error = str(exc)
            await db.flush()
            raise
        setattr(certificate, f"registered_{environment}_at", datetime.now(UTC))
        certificate.registration_error = None
        await db.flush()
        return certificate

    @staticmethod
    async def not_ready(db: AsyncSession, clinic_id: UUID) -> str | None:
        """Why the clinic cannot issue CFDIs yet, or ``None`` when it can."""
        clinic = await db.get(Clinic, clinic_id)
        rfc = (clinic.tax_id or "").strip().upper() if clinic else ""
        if not RFC.match(rfc):
            return "Para facturar ante el SAT, el RFC de la clínica tiene que ser válido."
        if not (clinic.legal_name or "").strip():
            return (
                "Para facturar ante el SAT, falta la razón social de la clínica, "
                "tal como aparece en su constancia de situación fiscal."
            )
        settings = await SatIssuerService.get_settings(db, clinic_id)
        if settings is None or not settings.tax_regime or not settings.expedition_postal_code:
            return (
                "Para facturar ante el SAT, faltan el régimen fiscal y el código postal "
                "de expedición."
            )
        environment = _ENVIRONMENT_NAMES[settings.environment]
        if not (
            settings.facturama_user(settings.environment)
            and getattr(settings, f"facturama_{settings.environment}_password_encrypted")
        ):
            return (
                "Para facturar ante el SAT, faltan el usuario y la contraseña de Facturama "
                f"de la clínica (entorno de {environment})."
            )
        certificate = await SatIssuerService.active_certificate(db, clinic_id)
        if certificate is None:
            return "Para facturar ante el SAT, falta el CSD de la clínica."
        if certificate.rfc != rfc:
            return "Para facturar ante el SAT, el CSD activo es de otro RFC; súbelo de nuevo."
        if certificate.valid_until < datetime.now(UTC):
            return (
                f"Para facturar ante el SAT, renueva el CSD: caducó el "
                f"{certificate.valid_until:%d/%m/%Y}."
            )
        if not certificate.is_registered_in(settings.environment):
            missing = (
                "Para facturar ante el SAT, registra el CSD en Facturama "
                f"(entorno de {_ENVIRONMENT_NAMES[settings.environment]})."
            )
            if certificate.registration_error:
                missing += f" Último intento: {certificate.registration_error}"
            return missing
        if not settings.product_code:
            return (
                "Para facturar ante el SAT, falta la clave de producto o servicio "
                "(c_ClaveProdServ) de los conceptos."
            )
        return None
