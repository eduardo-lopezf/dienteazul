"""What the record genuinely owns: the disclosures made of it.

Everything a record *says* belongs to the module that recorded it. What is
new, and nobody else's, is the act of handing the record to someone: who
received it, why, on what evidence, what exactly it contained
([ADR 0033](../../../../docs/adr/0033-disclosure-requires-a-recorded-authorisation.md)).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.core.ids import uuid7
from app.core.privacy import PiiKind, pii
from app.database import Base, TimestampMixin

#: Why the record leaves. The purpose decides what evidence is asked for.
PURPOSES = ("continuity_of_care", "patient_copy", "authorised_third_party", "legal_requirement")


class Disclosure(Base, TimestampMixin):
    """One handing-over of a patient's record. Never edited, never deleted."""

    __tablename__ = "record_disclosure"
    __table_args__ = (Index("ix_record_disclosure_patient", "clinic_id", "patient_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), nullable=False)

    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    #: Who receives it: a person or an institution, as the clinic names them.
    recipient_name: Mapped[str] = mapped_column(String(200), nullable=False, info=pii(PiiKind.NAME))
    #: The evidence the purpose asks for, in the clinic's words: the clinical
    #: justification of a referral, the authorisation the patient signed, the
    #: order of an authority.
    evidence: Mapped[str | None] = mapped_column(Text)
    #: ``patient_copy``: whoever handed it over checked who was asking.
    identity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: The sections asked for, by qualified name (``module.section``).
    scope: Mapped[list] = mapped_column(JSONB, nullable=False)
    #: What was actually included: per section, the source of every entry.
    #: Permission and payload drift apart, so both are kept.
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)

    #: The document exactly as it left, and its SHA-256. "What did they
    #: receive" is answered by this, not by regenerating it — the record
    #: has moved on since.
    document: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locale: Mapped[str] = mapped_column(String(5), nullable=False, default="es")

    #: The account that produced it, and the professional it answers to.
    disclosed_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    disclosed_by_professional_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
