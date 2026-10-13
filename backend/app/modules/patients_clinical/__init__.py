"""patients_clinical — normalized medical history + emergency contacts.

Extracted from the JSONB blobs that lived on ``patients`` before Fase
B.4. Tables live under the ``patients_clinical_*`` prefix, one row per
allergy/medication/etc. (N:1 to patient) or per patient
(medical_context, emergency_contact, legal_guardian — all 1:1).

This module owns the ``patient.medical_updated`` event emission so the
timeline stays populated after the JSONB column is gone.
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import (
    Allergy,
    AsaAssessment,
    EmergencyContact,
    FamilyHistory,
    HealthQuestionnaire,
    LegalGuardian,
    MedicalContext,
    Medication,
    SurgicalHistory,
    SystemicDisease,
)
from .router import router


class PatientsClinicalModule(BaseModule):
    """Normalized medical history + emergency contacts."""

    manifest = {
        "name": "patients_clinical",
        "version": "0.1.0",
        "summary": "Normalized medical history, allergies, medications, emergency contacts.",
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["patients"],
        # `professionals` owns the directory a clinical entry is attributed to
        # (ADR 0032). The FK is ordered across branches with `depends_on` in
        # `pc_0003`, the way `liquidations` does it. Optional (ADR 0037):
        # with the directory off, an entry names no professional.
        "integrates": ["professionals"],
        "installable": True,
        "auto_install": True,
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            # `asa.write` is its own permission: an ASA class is a clinical
            # judgement, and a clinic may let someone edit the history
            # without letting them make it.
            #
            # `asa.read` is the class alone — "ASA III" — for whoever books
            # the patient. No date, no history, no reason, no assessor: reception needs to know the patient asks
            # for care in the scheduling, not why.
            "dentist": [
                "medical.read",
                "medical.write",
                "asa.read",
                "asa.write",
                "emergency.read",
                "emergency.write",
            ],
            "hygienist": ["medical.read", "asa.read", "emergency.read"],
            "assistant": ["medical.read", "asa.read", "emergency.read", "emergency.write"],
            "receptionist": ["asa.read", "emergency.read", "emergency.write"],
        },
        "frontend": {
            "layer_path": "frontend",
        },
    }

    def get_models(self) -> list:
        return [
            MedicalContext,
            Allergy,
            Medication,
            SystemicDisease,
            SurgicalHistory,
            FamilyHistory,
            HealthQuestionnaire,
            AsaAssessment,
            EmergencyContact,
            LegalGuardian,
        ]

    def get_router(self) -> APIRouter:
        return router

    def get_record_sections(self) -> list:
        from . import record

        return record.get_record_sections()

    def get_subject_contributors(self) -> list:
        from . import privacy

        return privacy.get_subject_contributors()

    def get_permissions(self) -> list[str]:
        return [
            "medical.read",
            "medical.write",
            "asa.read",
            "asa.write",
            "emergency.read",
            "emergency.write",
        ]
