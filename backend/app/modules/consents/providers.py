"""What consents offers other modules without being imported (ADR 0039)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.contracts import ProfessionalDirectory, provider

from .models import Consent

SETTINGS_KEY = "consents"
REQUIRE_FOR_PLAN = "require_informed_for_plan"


def requires_informed_for_plan(clinic: Clinic | None) -> bool:
    """Whether this clinic asks for a signed informed consent before a
    treatment plan is confirmed. Only when it said so: the letter is not
    mandatory until the clinic switches the rule on."""
    stored = ((clinic.settings or {}) if clinic else {}).get(SETTINGS_KEY) or {}
    return stored.get(REQUIRE_FOR_PLAN) is True


class ConsentsPlanConsents:
    async def lacks_required_consent(
        self, db: AsyncSession, clinic_id: UUID, patient_id: UUID, plan_id: UUID
    ) -> bool:
        if not requires_informed_for_plan(await db.get(Clinic, clinic_id)):
            return False
        # An informed consent names the professional who explained it. With
        # the directory off none can be signed, and a rule nobody can meet
        # would stop every plan.
        if provider(ProfessionalDirectory) is None:
            return False
        signed = await db.execute(
            select(Consent.id)
            .where(
                Consent.clinic_id == clinic_id,
                Consent.patient_id == patient_id,
                Consent.plan_id == plan_id,
                Consent.kind == "informed",
                # Signed and still standing: a revoked letter no longer consents.
                Consent.status == "signed",
            )
            .limit(1)
        )
        return signed.scalar_one_or_none() is None


plan_consents = ConsentsPlanConsents()
