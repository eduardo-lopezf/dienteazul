"""Odontogram module - dental charting and treatment tracking."""

import logging

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import (
    OdontogramClinicSettings,
    OdontogramHistory,
    OdontogramPreference,
    ToothRecord,
    Treatment,
    TreatmentTooth,
)
from .router import router

logger = logging.getLogger(__name__)


class OdontogramModule(BaseModule):
    """Odontogram module: tooth state + clinical treatments."""

    manifest = {
        "name": "odontogram",
        "version": "0.3.0",
        "summary": "Dental charting, tooth state, clinical treatments.",
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["patients", "catalog"],
        "installable": True,
        "auto_install": True,
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["*"],
            "hygienist": ["read", "write"],
            "assistant": ["read"],
            "receptionist": [],
        },
        "frontend": {
            "layer_path": "frontend",
        },
    }

    def get_models(self) -> list:
        return [
            ToothRecord,
            OdontogramHistory,
            Treatment,
            TreatmentTooth,
            OdontogramPreference,
            OdontogramClinicSettings,
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
            "read",
            "write",
            "treatments.read",
            "treatments.write",
        ]

    def get_event_handlers(self) -> dict:
        # Propagation from plan -> treatment performed now lives directly in
        # TreatmentPlanService.complete_item, so no subscriptions are needed here.
        return {}
