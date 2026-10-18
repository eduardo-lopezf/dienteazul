"""Professionals module — clinic dentists and collaborators directory."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import Professional
from .router import router


class ProfessionalsModule(BaseModule):
    """Owns the clinic-scoped directory of dentists and collaborators."""

    manifest = {
        "name": "professionals",
        "version": "0.1.0",
        "summary": (
            "Who the work is assigned to: the holder of an individual practice, "
            "or a clinic's directory of professionals."
        ),
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["media", "catalog"],  # catalog owns `specialties` (FK target)
        "installable": True,
        "auto_install": True,
        "removable": True,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["read"],
            "hygienist": ["read"],
            "assistant": ["read"],
            "receptionist": ["read"],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [
                {
                    "label": "professionals.nav",
                    "icon": "i-lucide-stethoscope",
                    "to": "/professionals",
                    "permission": "professionals.read",
                    "order": 45,
                    # One professional's practice has a single profile, its
                    # holder's, edited from their account settings: the
                    # directory is a clinic's screen.
                    "tiers": ["clinic", "clinic_pro", "hospital"],
                },
            ],
        },
    }

    def get_models(self) -> list:
        return [Professional]

    def get_event_handlers(self) -> dict:
        from app.core.events import EventType

        from .events import on_clinic_account_tier_changed, on_clinic_created

        return {
            EventType.CLINIC_CREATED: on_clinic_created,
            EventType.CLINIC_ACCOUNT_TIER_CHANGED: on_clinic_account_tier_changed,
        }

    def get_providers(self) -> dict[type, object]:
        from app.core.contracts import ProfessionalDirectory

        from .providers import professionals_directory

        return {ProfessionalDirectory: professionals_directory}

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["read", "write"]
