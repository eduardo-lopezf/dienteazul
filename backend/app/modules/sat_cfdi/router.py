"""SAT module FastAPI router.

Endpoints under ``/api/v1/sat_cfdi/``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.core.server_errors import slow_budget
from app.database import get_db

from .csd import CsdError
from .errors import certificate_error, certificate_missing, pac_error, rfc_invalid
from .issuer import CertificateMissingError, SatIssuerService
from .pac import TIMEOUT as PAC_TIMEOUT
from .pac import PacError
from .receivers import SatReceiverService
from .schemas import (
    FacturamaAccountOut,
    FacturamaCredentialsIn,
    SatCertificateOut,
    SatCfdiOut,
    SatReceiverIn,
    SatReceiverOut,
    SatSettingsIn,
    SatSettingsOut,
    valid_rfc,
)
from .service import SatCfdiService

# No prefix: `_mount_one` mounts every module router at ``/api/v1/<module name>``.
router = APIRouter(tags=["sat_cfdi"])

#: Registering a CSD waits on Facturama, so a healthy answer takes seconds
#: (``SLOW_REQUEST_SECONDS`` is five). Past the PAC's own timeout the wait
#: is ours, not theirs, and worth recording.
PAC_WAIT = PAC_TIMEOUT + 5.0


@router.get("/invoices/{invoice_id}/cfdis", response_model=ApiResponse[list[SatCfdiOut]])
async def list_invoice_cfdis(
    invoice_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("sat_cfdi.cfdi.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[SatCfdiOut]]:
    """The CFDIs of one invoice of the clinic, oldest first."""
    rows = await SatCfdiService.list_for_invoice(db, ctx.clinic_id, invoice_id)
    return ApiResponse(data=[SatCfdiOut.model_validate(row) for row in rows])


async def _settings_out(db: AsyncSession, ctx: ClinicContext) -> SatSettingsOut:
    settings = await SatIssuerService.get_settings(db, ctx.clinic_id)
    certificate = await SatIssuerService.active_certificate(db, ctx.clinic_id)
    missing = await SatIssuerService.not_ready(db, ctx.clinic_id)
    return SatSettingsOut(
        rfc=ctx.clinic.tax_id,
        legal_name=ctx.clinic.legal_name,
        tax_regime=settings.tax_regime if settings else None,
        expedition_postal_code=settings.expedition_postal_code if settings else None,
        environment=settings.environment if settings else "sandbox",
        product_code=settings.product_code if settings else None,
        unit_code=settings.unit_code if settings else "E48",
        stamp_delay_minutes=settings.stamp_delay_minutes if settings else 30,
        facturama={
            environment: FacturamaAccountOut(
                user=settings.facturama_user(environment) if settings else None,
                has_password=bool(
                    settings and getattr(settings, f"facturama_{environment}_password_encrypted")
                ),
            )
            for environment in ("sandbox", "production")
        },
        certificate=SatCertificateOut.model_validate(certificate) if certificate else None,
        ready=missing is None,
        missing=missing,
    )


@router.get("/settings", response_model=ApiResponse[SatSettingsOut])
async def get_settings(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("sat_cfdi.settings.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SatSettingsOut]:
    """The clinic as issuer: its RFC and name, the SAT settings, its CSD."""
    return ApiResponse(data=await _settings_out(db, ctx))


@router.put("/settings", response_model=ApiResponse[SatSettingsOut])
async def save_settings(
    data: SatSettingsIn,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("sat_cfdi.settings.configure"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SatSettingsOut]:
    await SatIssuerService.save_settings(
        db,
        ctx.clinic_id,
        tax_regime=data.tax_regime,
        expedition_postal_code=data.expedition_postal_code,
        environment=data.environment,
        product_code=data.product_code,
        unit_code=data.unit_code,
        stamp_delay_minutes=data.stamp_delay_minutes,
    )
    return ApiResponse(data=await _settings_out(db, ctx))


@router.put("/facturama-credentials", response_model=ApiResponse[SatSettingsOut])
async def save_facturama_credentials(
    data: FacturamaCredentialsIn,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("sat_cfdi.settings.configure"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SatSettingsOut]:
    """The clinic's own Facturama account for one environment. The password
    is stored encrypted and never returned; omitted, the stored one stays."""
    await SatIssuerService.save_credentials(
        db,
        ctx.clinic_id,
        environment=data.environment,
        user=data.user,
        password=data.password,
    )
    return ApiResponse(data=await _settings_out(db, ctx))


@router.post("/certificate", response_model=ApiResponse[SatCertificateOut], status_code=201)
@slow_budget(PAC_WAIT)
async def upload_certificate(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("sat_cfdi.settings.configure"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    cer: Annotated[UploadFile, File(description="Certificado del CSD (.cer)")],
    key: Annotated[UploadFile, File(description="Llave privada del CSD (.key)")],
    password: Annotated[str, Form(description="Contraseña de la llave privada")],
) -> ApiResponse[SatCertificateOut]:
    """Upload the clinic's CSD and register it with Facturama. It replaces
    the active one."""
    try:
        certificate = await SatIssuerService.upload_certificate(
            db,
            ctx.clinic,
            cer=await cer.read(),
            key=await key.read(),
            password=password,
            uploaded_by=ctx.user_id,
        )
    except CsdError as exc:
        raise certificate_error(exc) from exc
    except PacError as exc:
        raise pac_error(exc) from exc
    return ApiResponse(data=SatCertificateOut.model_validate(certificate))


@router.post("/certificate/register", response_model=ApiResponse[SatCertificateOut])
@slow_budget(PAC_WAIT)
async def register_certificate(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("sat_cfdi.settings.configure"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SatCertificateOut]:
    """Register the active CSD with Facturama in the clinic's environment —
    after Facturama did not answer, or when the environment changed."""
    try:
        certificate = await SatIssuerService.register_active(db, ctx.clinic_id)
    except CertificateMissingError as exc:
        raise certificate_missing(str(exc)) from exc
    except CsdError as exc:
        raise certificate_error(exc) from exc
    except PacError as exc:
        raise pac_error(exc) from exc
    return ApiResponse(data=SatCertificateOut.model_validate(certificate))


def _rfc(rfc: str) -> str:
    try:
        return valid_rfc(rfc)
    except ValueError as exc:
        raise rfc_invalid(rfc) from exc


@router.get("/receivers/{rfc}", response_model=ApiResponse[SatReceiverOut | None])
async def get_receiver(
    rfc: str,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("sat_cfdi.cfdi.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SatReceiverOut | None]:
    """A receiver's fiscal profile, or ``null`` when there is none yet."""
    receiver = await SatReceiverService.get(db, ctx.clinic_id, _rfc(rfc))
    return ApiResponse(data=SatReceiverOut.model_validate(receiver) if receiver else None)


@router.put("/receivers/{rfc}", response_model=ApiResponse[SatReceiverOut])
async def save_receiver(
    rfc: str,
    data: SatReceiverIn,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("sat_cfdi.receiver.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SatReceiverOut]:
    receiver = await SatReceiverService.save(
        db,
        ctx.clinic_id,
        _rfc(rfc),
        tax_regime=data.tax_regime,
        tax_zip_code=data.tax_zip_code,
        cfdi_use=data.cfdi_use,
    )
    return ApiResponse(data=SatReceiverOut.model_validate(receiver))
