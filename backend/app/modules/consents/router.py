"""HTTP API for consent letters and their templates."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.errors import AppError
from app.core.schemas import ApiResponse
from app.database import get_db

from .errors import consent_domain_error, consents_error
from .pdf import render_pdf
from .providers import REQUIRE_FOR_PLAN, SETTINGS_KEY, requires_informed_for_plan
from .schemas import (
    ConsentCreate,
    ConsentNote,
    ConsentResponse,
    ConsentSettings,
    ConsentSign,
    ConsentUpdate,
    Kind,
    TemplateCreate,
    TemplateResponse,
    TemplateUpdate,
)
from .service import ConsentError, ConsentService, ConsentStateError, TemplateService

router = APIRouter()

Ctx = Annotated[ClinicContext, Depends(get_clinic_context)]
Db = Annotated[AsyncSession, Depends(get_db)]
CanRead = Annotated[None, Depends(require_permission("consents.read"))]
CanWrite = Annotated[None, Depends(require_permission("consents.write"))]
CanEditTemplates = Annotated[None, Depends(require_permission("consents.templates.write"))]


def _refuse(error: ConsentError) -> AppError:
    return consent_domain_error(str(error), state_error=isinstance(error, ConsentStateError))


# --- Templates ---------------------------------------------------------------


@router.get("/settings", response_model=ApiResponse[ConsentSettings])
async def get_settings(ctx: Ctx, _: CanRead) -> ApiResponse[ConsentSettings]:
    """Whether a plan needs a signed informed consent to be confirmed."""
    return ApiResponse(
        data=ConsentSettings(require_informed_for_plan=requires_informed_for_plan(ctx.clinic))
    )


@router.put("/settings", response_model=ApiResponse[ConsentSettings])
async def update_settings(
    data: ConsentSettings, ctx: Ctx, _: CanEditTemplates, db: Db
) -> ApiResponse[ConsentSettings]:
    clinic = ctx.clinic
    clinic.settings = {
        **(clinic.settings or {}),
        SETTINGS_KEY: {
            **((clinic.settings or {}).get(SETTINGS_KEY) or {}),
            REQUIRE_FOR_PLAN: data.require_informed_for_plan,
        },
    }
    await db.commit()
    await db.refresh(clinic)
    return ApiResponse(
        data=ConsentSettings(require_informed_for_plan=requires_informed_for_plan(clinic))
    )


@router.get("/templates", response_model=ApiResponse[list[TemplateResponse]])
async def list_templates(
    ctx: Ctx,
    _: CanRead,
    db: Db,
    kind: Kind | None = None,
    include_inactive: bool = Query(default=False),
) -> ApiResponse[list[TemplateResponse]]:
    templates = await TemplateService.list(
        db, ctx.clinic_id, kind=kind, include_inactive=include_inactive
    )
    return ApiResponse(data=[TemplateResponse.model_validate(t) for t in templates])


@router.post("/templates", response_model=ApiResponse[TemplateResponse], status_code=201)
async def create_template(
    data: TemplateCreate, ctx: Ctx, _: CanEditTemplates, db: Db
) -> ApiResponse[TemplateResponse]:
    template = await TemplateService.create(db, ctx.clinic_id, ctx.user_id, data.model_dump())
    return ApiResponse(data=TemplateResponse.model_validate(template))


@router.put("/templates/{template_id}", response_model=ApiResponse[TemplateResponse])
async def update_template(
    template_id: UUID, data: TemplateUpdate, ctx: Ctx, _: CanEditTemplates, db: Db
) -> ApiResponse[TemplateResponse]:
    template = await TemplateService.get(db, ctx.clinic_id, template_id)
    if template is None:
        raise consents_error("consents.template.not_found")
    template = await TemplateService.update(db, template, data.model_dump(exclude_unset=True))
    return ApiResponse(data=TemplateResponse.model_validate(template))


# --- Consents ----------------------------------------------------------------


async def _consent(db: AsyncSession, ctx: ClinicContext, consent_id: UUID):
    consent = await ConsentService.get(db, ctx.clinic_id, consent_id)
    if consent is None:
        raise consents_error("consents.consent.not_found")
    return consent


@router.get("/patients/{patient_id}", response_model=ApiResponse[list[ConsentResponse]])
async def list_patient_consents(
    patient_id: UUID, ctx: Ctx, _: CanRead, db: Db
) -> ApiResponse[list[ConsentResponse]]:
    consents = await ConsentService.list_for_patient(db, ctx.clinic_id, patient_id)
    return ApiResponse(data=[ConsentResponse.model_validate(c) for c in consents])


@router.post("/patients/{patient_id}", response_model=ApiResponse[ConsentResponse], status_code=201)
async def create_consent(
    patient_id: UUID, data: ConsentCreate, ctx: Ctx, _: CanWrite, db: Db
) -> ApiResponse[ConsentResponse]:
    """Write a draft consent for a patient, from a template or from scratch."""
    try:
        consent = await ConsentService.create(
            db, ctx.clinic_id, patient_id, ctx.user_id, data.model_dump()
        )
    except ConsentError as error:
        raise _refuse(error) from error
    return ApiResponse(data=ConsentResponse.model_validate(consent))


@router.get("/{consent_id}", response_model=ApiResponse[ConsentResponse])
async def get_consent(
    consent_id: UUID, ctx: Ctx, _: CanRead, db: Db
) -> ApiResponse[ConsentResponse]:
    return ApiResponse(data=ConsentResponse.model_validate(await _consent(db, ctx, consent_id)))


@router.get("/{consent_id}/pdf")
async def consent_pdf(
    consent_id: UUID,
    ctx: Ctx,
    _: CanRead,
    db: Db,
    locale: str = Query(default="es", pattern="^(es|en)$"),
) -> Response:
    """The letter as a print-ready sheet (served inline).

    A draft prints as a form to fill in and sign by hand; a letter signed
    on screen prints with its signature.
    """
    consent = await _consent(db, ctx, consent_id)
    pdf = await render_pdf(db, consent, locale)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="consentimiento_{consent.id.hex[:8]}.pdf"'
        },
    )


@router.put("/{consent_id}", response_model=ApiResponse[ConsentResponse])
async def update_consent(
    consent_id: UUID, data: ConsentUpdate, ctx: Ctx, _: CanWrite, db: Db
) -> ApiResponse[ConsentResponse]:
    """Edit a draft. A signed, declined or revoked consent is a record."""
    consent = await _consent(db, ctx, consent_id)
    try:
        consent = await ConsentService.update(db, consent, data.model_dump(exclude_unset=True))
    except ConsentError as error:
        raise _refuse(error) from error
    return ApiResponse(data=ConsentResponse.model_validate(consent))


@router.post("/{consent_id}/sign", response_model=ApiResponse[ConsentResponse])
async def sign_consent(
    consent_id: UUID, data: ConsentSign, ctx: Ctx, _: CanWrite, db: Db
) -> ApiResponse[ConsentResponse]:
    consent = await _consent(db, ctx, consent_id)
    try:
        consent = await ConsentService.sign(db, consent, ctx.user_id, data.model_dump())
    except ConsentError as error:
        raise _refuse(error) from error
    return ApiResponse(data=ConsentResponse.model_validate(consent))


@router.post("/{consent_id}/decline", response_model=ApiResponse[ConsentResponse])
async def decline_consent(
    consent_id: UUID, data: ConsentNote, ctx: Ctx, _: CanWrite, db: Db
) -> ApiResponse[ConsentResponse]:
    """Record that the patient read it and did not accept."""
    consent = await _consent(db, ctx, consent_id)
    try:
        consent = await ConsentService.decline(db, consent, ctx.user_id, data.note)
    except ConsentError as error:
        raise _refuse(error) from error
    return ApiResponse(data=ConsentResponse.model_validate(consent))


@router.post("/{consent_id}/revoke", response_model=ApiResponse[ConsentResponse])
async def revoke_consent(
    consent_id: UUID, data: ConsentNote, ctx: Ctx, _: CanWrite, db: Db
) -> ApiResponse[ConsentResponse]:
    """Take a signed consent back from now on. Nothing is erased."""
    consent = await _consent(db, ctx, consent_id)
    try:
        consent = await ConsentService.revoke(db, consent, data.note)
    except ConsentError as error:
        raise _refuse(error) from error
    return ApiResponse(data=ConsentResponse.model_validate(consent))


@router.post("/{consent_id}/discard", response_model=ApiResponse[ConsentResponse])
async def discard_consent(
    consent_id: UUID, ctx: Ctx, _: CanWrite, db: Db
) -> ApiResponse[ConsentResponse]:
    """Drop a draft nobody signed."""
    consent = await _consent(db, ctx, consent_id)
    try:
        consent = await ConsentService.discard(db, consent)
    except ConsentError as error:
        raise _refuse(error) from error
    return ApiResponse(data=ConsentResponse.model_validate(consent))
