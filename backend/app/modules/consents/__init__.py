"""consents — consent letters: informed consent and consent to data use.

Part of the Clinical record App. The first of the pieces that implement
NOM-004-SSA3-2012 and Ley General de Salud Art. 51 Bis 1 for the dental
record: the letter in which a patient is told about a procedure, its risks
and its alternatives by a named professional, and accepts or declines.

It also holds the consent to the processing of personal data, which shares
the mechanism — a text, a signature, a revocation — and none of the meaning.
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import Consent, ConsentTemplate
from .router import router


class ConsentsModule(BaseModule):
    manifest = {
        "name": "consents",
        "version": "0.1.0",
        "summary": "Consent letters: informed consent to treat and consent to data use.",
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        # The patient the letter is about: a foreign key, and no consent
        # without one.
        "depends": ["patients"],
        # Who explained it is read through `ProfessionalDirectory` and kept
        # as a snapshot (ADR 0039). With the directory off, drafts and
        # data-use consents still work; an informed consent cannot be
        # signed, because it has to name a professional.
        #
        # A letter signed on paper is filed as a scan among the patient's
        # documents, checked through `PatientDocuments`. With Media off a
        # consent can still be printed and signed on screen.
        "integrates": ["professionals", "media"],
        "installable": True,
        # Off by default, like the rest of the Clinical record App.
        "auto_install": False,
        # A signed consent is evidence. The module is disabled, never
        # uninstalled (ADR 0035).
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["read", "write", "templates.write"],
            "hygienist": ["read", "write"],
            "assistant": ["read", "write"],
            "receptionist": ["read", "write"],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [],
        },
    }

    def get_models(self) -> list:
        return [ConsentTemplate, Consent]

    def get_router(self) -> APIRouter:
        return router

    def get_providers(self) -> dict[type, object]:
        from app.core.contracts import PlanConsents

        from .providers import plan_consents

        return {PlanConsents: plan_consents}

    def get_permissions(self) -> list[str]:
        return ["read", "write", "templates.write"]

    def get_record_sections(self) -> list:
        from . import record

        return record.get_record_sections()

    def get_subject_contributors(self) -> list:
        from . import privacy

        return privacy.get_subject_contributors()

    def get_tools(self) -> list:
        # None yet. Reading a consent out to an agent hands it a signature
        # and free text; writing one is a clinical act with a person's name
        # on it. Both wait for a reason to exist.
        return []
