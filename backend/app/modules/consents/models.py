"""Consent letters and the templates they are written from.

Two kinds of consent live here, and the clinic calls both *consentimiento*:

- ``informed`` — the patient understood the procedure, its risks and its
  alternatives, and accepts (Ley General de Salud Art. 51 Bis 1; the
  *cartas de consentimiento informado* of NOM-004-SSA3-2012).
- ``conformity`` — the patient states they are satisfied with a treatment
  that has been concluded (the *firma de conformidad* of a paper chart).
- ``data_use`` — the patient consents to the clinic processing their
  personal data, against the privacy notice shown to them.

A consent is a clinical record entry (ADR 0032): once signed it is never
edited or deleted. A patient taking it back is a **revocation** — a state
and a date added to the same row — because "what did they agree to, and
until when" has to stay answerable.

The text the patient saw is copied onto the consent (``body``); the
template can change afterwards without rewriting what anybody signed.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.privacy import PiiKind, pii
from app.database import Base, TimestampMixin

KINDS = ("informed", "data_use", "conformity")

#: ``draft`` is being written and binds nobody. ``signed``, ``declined`` and
#: ``revoked`` are facts about the patient and stay. ``discarded`` is a draft
#: nobody signed, kept out of sight.
STATUSES = ("draft", "signed", "declined", "revoked", "discarded")

SIGNER_CAPACITIES = ("patient", "guardian", "representative")

#: ``screen`` — drawn on the tablet. ``paper`` — the printed letter, filled
#: in and signed by hand, scanned and filed with the patient's documents.
SIGNATURE_METHODS = ("screen", "paper")


class ConsentTemplate(Base, TimestampMixin):
    """A text the clinic reuses: one per procedure, or the privacy notice."""

    __tablename__ = "consents_template"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: Bumped on every edit. A consent records the version it was written
    #: from, which is what "which privacy notice did they accept" needs.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


class Consent(Base, TimestampMixin):
    __tablename__ = "consents_consent"
    __table_args__ = (Index("ix_consents_consent_patient", "clinic_id", "patient_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), nullable=False)

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: What the patient was shown. A copy, not a pointer to the template.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    template_id: Mapped[UUID | None] = mapped_column(ForeignKey("consents_template.id"))
    template_version: Mapped[int | None] = mapped_column(Integer)

    #: What the consent is about, in the clinic's words ("Extracción del 48").
    procedure_label: Mapped[str | None] = mapped_column(String(200))
    #: The treatment plan it belongs to, when there is one. No foreign key:
    #: the plan is another App's row (ADR 0042) and may not be running.
    plan_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))

    # Who explained it. Art. 51 Bis 1 is an obligation on a person, so an
    # informed consent names one. Id without a foreign key, plus the name
    # and licence as they were that day — the directory is another App, and
    # a letter must still read correctly after a professional leaves.
    explained_by_professional_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    explained_by_name: Mapped[str | None] = mapped_column(String(200), info=pii(PiiKind.NAME))
    explained_by_license: Mapped[str | None] = mapped_column(String(80))

    # The signature.
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_by_name: Mapped[str | None] = mapped_column(String(200), info=pii(PiiKind.NAME))
    #: In what capacity they signed: the patient, or someone for them.
    signer_capacity: Mapped[str | None] = mapped_column(String(20))
    signature_method: Mapped[str | None] = mapped_column(String(20))
    #: Method-specific: ``{"png": "data:image/png;base64,…"}`` for a tablet,
    #: ``{"document_id": "…"}`` for a scan. The scan is a row of the Media
    #: module — an id, not a foreign key (ADR 0042).
    signature_data: Mapped[dict | None] = mapped_column(JSONB)
    #: The regulation the letter named when it was signed — the clinic may
    #: change its line afterwards, and what was signed under stays.
    regulation: Mapped[str | None] = mapped_column(String(300))

    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Why it was declined or revoked, in the words of whoever recorded it.
    status_note: Mapped[str | None] = mapped_column(Text)

    #: The account that operated the software — the audit trail.
    recorded_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
