"""Business rules for consent letters."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.contracts import (
    PatientDirectory,
    PatientDocuments,
    ProfessionalDirectory,
    provider,
)
from app.core.regulation import record_regulation

from .models import Consent, ConsentTemplate

PROFESSIONALS_UNAVAILABLE = (
    "Professionals are not available — an informed consent must name who explained it"
)


class ConsentError(ValueError):
    """The request cannot be carried out as asked (maps to 400)."""


class ConsentStateError(ConsentError):
    """The consent is not in a state that allows it (maps to 409)."""


class TemplateService:
    @staticmethod
    async def list(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        kind: str | None = None,
        include_inactive: bool = False,
    ) -> list[ConsentTemplate]:
        query = select(ConsentTemplate).where(ConsentTemplate.clinic_id == clinic_id)
        if kind:
            query = query.where(ConsentTemplate.kind == kind)
        if not include_inactive:
            query = query.where(ConsentTemplate.is_active.is_(True))
        result = await db.execute(query.order_by(ConsentTemplate.title))
        return list(result.scalars())

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, template_id: UUID) -> ConsentTemplate | None:
        result = await db.execute(
            select(ConsentTemplate).where(
                ConsentTemplate.id == template_id, ConsentTemplate.clinic_id == clinic_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession, clinic_id: UUID, user_id: UUID, data: dict
    ) -> ConsentTemplate:
        template = ConsentTemplate(clinic_id=clinic_id, created_by=user_id, **data)
        db.add(template)
        await db.flush()
        return template

    @staticmethod
    async def update(db: AsyncSession, template: ConsentTemplate, data: dict) -> ConsentTemplate:
        """Edit a template. A change of wording is a new version.

        Consents already written keep the text they were written with —
        they hold a copy — so editing never rewrites what anybody signed.
        """
        reworded = any(
            key in data and data[key] != getattr(template, key) for key in ("title", "body")
        )
        for key, value in data.items():
            setattr(template, key, value)
        if reworded:
            template.version += 1
        await db.flush()
        return template


class ConsentService:
    @staticmethod
    async def list_for_patient(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID, *, include_discarded: bool = False
    ) -> list[Consent]:
        query = select(Consent).where(
            Consent.clinic_id == clinic_id, Consent.patient_id == patient_id
        )
        if not include_discarded:
            query = query.where(Consent.status != "discarded")
        result = await db.execute(query.order_by(Consent.created_at.desc()))
        return list(result.scalars())

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, consent_id: UUID) -> Consent | None:
        result = await db.execute(
            select(Consent).where(Consent.id == consent_id, Consent.clinic_id == clinic_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _explained_by(
        db: AsyncSession, clinic_id: UUID, professional_id: UUID | None
    ) -> dict:
        """Who explained it, as a snapshot: id, name and licence that day.

        Asked of the directory's contract (ADR 0039). With the Professionals
        App off nobody can be named.
        """
        if professional_id is None:
            return {
                "explained_by_professional_id": None,
                "explained_by_name": None,
                "explained_by_license": None,
            }
        directory = provider(ProfessionalDirectory)
        if directory is None:
            raise ConsentError(PROFESSIONALS_UNAVAILABLE)
        brief = (await directory.briefs(db, clinic_id, [professional_id])).get(professional_id)
        if brief is None:
            raise ConsentError("Professional not found in this clinic")
        return {
            "explained_by_professional_id": brief.id,
            "explained_by_name": f"{brief.first_name} {brief.last_name}".strip(),
            "explained_by_license": brief.license_number,
        }

    @staticmethod
    async def create(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID, user_id: UUID, data: dict
    ) -> Consent:
        """Write a draft, from a template or from scratch."""
        patients = provider(PatientDirectory)
        if patients is None or not await patients.is_bookable(db, clinic_id, patient_id):
            raise ConsentError("Patient not found in this clinic")

        title, body = data.get("title"), data.get("body")
        template_version = None
        if data.get("template_id"):
            template = await TemplateService.get(db, clinic_id, data["template_id"])
            if template is None or template.kind != data["kind"]:
                raise ConsentError("Template not found for this kind of consent")
            title, body = title or template.title, body or template.body
            template_version = template.version
        if not title or not body:
            raise ConsentError("A consent needs a title and a text")

        consent = Consent(
            clinic_id=clinic_id,
            patient_id=patient_id,
            kind=data["kind"],
            status="draft",
            title=title,
            body=body,
            template_id=data.get("template_id"),
            template_version=template_version,
            procedure_label=data.get("procedure_label"),
            plan_id=data.get("plan_id"),
            recorded_by_user_id=user_id,
            **await ConsentService._explained_by(
                db, clinic_id, data.get("explained_by_professional_id")
            ),
        )
        db.add(consent)
        await db.flush()
        return consent

    @staticmethod
    async def update(db: AsyncSession, consent: Consent, data: dict) -> Consent:
        """Edit a draft. Anything else is a record and stays as it is."""
        if consent.status != "draft":
            raise ConsentStateError("Only a draft can be edited")
        if "explained_by_professional_id" in data:
            for key, value in (
                await ConsentService._explained_by(
                    db, consent.clinic_id, data.pop("explained_by_professional_id")
                )
            ).items():
                setattr(consent, key, value)
        for key, value in data.items():
            setattr(consent, key, value)
        await db.flush()
        return consent

    @staticmethod
    async def sign(db: AsyncSession, consent: Consent, user_id: UUID, data: dict) -> Consent:
        if consent.status != "draft":
            raise ConsentStateError(f"Cannot sign a consent that is '{consent.status}'")
        # Art. 51 Bis 1 puts the duty to inform on a person. A letter that
        # names nobody proves a signature, not that anything was explained.
        if consent.kind == "informed" and consent.explained_by_professional_id is None:
            raise ConsentError("An informed consent must name the professional who explained it")

        method = data.get("method", "screen")
        signature = data.get("signature_data")
        if method == "paper":
            # The signature is on the sheet; what the record holds is the
            # scan. It has to be a file of this same patient — asked of the
            # documents' contract (ADR 0039), which is absent while the
            # Media module is off.
            documents = provider(PatientDocuments)
            if documents is None:
                raise ConsentError("Documents are not available — a scan cannot be filed")
            if not await documents.belongs_to(
                db, consent.clinic_id, consent.patient_id, data["document_id"]
            ):
                raise ConsentError("The scanned document is not one of this patient's files")
            signature = {"document_id": str(data["document_id"])}

        consent.status = "signed"
        consent.signed_at = datetime.now(UTC)
        consent.signed_by_name = data["signed_by_name"]
        consent.signer_capacity = data["signer_capacity"]
        consent.signature_method = method
        consent.signature_data = signature
        clinic = await db.get(Clinic, consent.clinic_id)
        consent.regulation = record_regulation(clinic) if clinic is not None else None
        consent.recorded_by_user_id = user_id
        await db.flush()
        return consent

    @staticmethod
    async def decline(
        db: AsyncSession, consent: Consent, user_id: UUID, note: str | None
    ) -> Consent:
        """The patient read it and said no. That is a fact worth keeping."""
        if consent.status != "draft":
            raise ConsentStateError(f"Cannot decline a consent that is '{consent.status}'")
        consent.status = "declined"
        consent.declined_at = datetime.now(UTC)
        consent.status_note = note
        consent.recorded_by_user_id = user_id
        await db.flush()
        return consent

    @staticmethod
    async def revoke(db: AsyncSession, consent: Consent, note: str | None) -> Consent:
        """Take a signed consent back, from now on.

        The signature and the text stay: what the patient agreed to, and
        until when, has to remain answerable (ADR 0032).
        """
        if consent.status != "signed":
            raise ConsentStateError("Only a signed consent can be revoked")
        consent.status = "revoked"
        consent.revoked_at = datetime.now(UTC)
        consent.status_note = note
        await db.flush()
        return consent

    @staticmethod
    async def discard(db: AsyncSession, consent: Consent) -> Consent:
        """Drop a draft nobody signed. It was never a record."""
        if consent.status != "draft":
            raise ConsentStateError("Only a draft can be discarded")
        consent.status = "discarded"
        await db.flush()
        return consent
