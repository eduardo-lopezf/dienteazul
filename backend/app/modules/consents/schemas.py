"""Pydantic schemas for the consents module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal["informed", "data_use", "conformity"]
SignerCapacity = Literal["patient", "guardian", "representative"]
SignatureMethod = Literal["screen", "paper"]


class TemplateCreate(BaseModel):
    kind: Kind
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)


class TemplateUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    title: str
    body: str
    version: int
    is_active: bool
    updated_at: datetime


class ConsentSettings(BaseModel):
    """How this clinic uses consent letters."""

    #: A treatment plan is not confirmed without a signed informed consent
    #: written for it.
    require_informed_for_plan: bool = False


class ConsentCreate(BaseModel):
    """A draft, written from a template or from scratch."""

    kind: Kind
    template_id: UUID | None = None
    title: str | None = Field(default=None, max_length=200)
    body: str | None = None
    procedure_label: str | None = Field(default=None, max_length=200)
    plan_id: UUID | None = None
    explained_by_professional_id: UUID | None = None


class ConsentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1)
    procedure_label: str | None = Field(default=None, max_length=200)
    explained_by_professional_id: UUID | None = None


class ConsentSign(BaseModel):
    signed_by_name: str = Field(min_length=1, max_length=200)
    signer_capacity: SignerCapacity = "patient"
    method: SignatureMethod = "screen"
    #: ``{"png": "data:image/png;base64,…"}`` from the tablet canvas.
    signature_data: dict | None = None
    #: ``paper``: the scan of the signed letter, already uploaded to the
    #: patient's documents.
    document_id: UUID | None = None

    @model_validator(mode="after")
    def _paper_needs_its_scan(self) -> ConsentSign:
        if self.method == "paper" and self.document_id is None:
            raise ValueError("A consent signed on paper needs the scanned document")
        return self


class ConsentNote(BaseModel):
    """Why a consent was declined, revoked or discarded."""

    note: str | None = Field(default=None, max_length=2000)


class ConsentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    kind: str
    status: str
    title: str
    body: str
    template_id: UUID | None
    template_version: int | None
    procedure_label: str | None
    plan_id: UUID | None
    explained_by_professional_id: UUID | None
    explained_by_name: str | None
    explained_by_license: str | None
    signed_at: datetime | None
    signed_by_name: str | None
    signer_capacity: str | None
    signature_method: str | None
    signature_data: dict | None
    #: The regulation the letter named when it was signed.
    regulation: str | None
    declined_at: datetime | None
    revoked_at: datetime | None
    status_note: str | None
    created_at: datetime
    updated_at: datetime
