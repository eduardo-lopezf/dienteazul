"""Catalog module - treatment catalog management."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import (
    Specialty,
    TreatmentCatalogItem,
    TreatmentCategory,
    TreatmentOdontogramMapping,
)
from .router import router


class CatalogModule(BaseModule):
    """Catalog module providing treatment catalog management.

    This module serves as the foundation for Diente Azul's revenue workflow:
    Catalog → Budgets → Billing.

    MVP Features:
    - Internal codes (clinic's own treatment codes)
    - Single price list (default prices per treatment)
    - VAT handling (healthcare exempt vs cosmetic taxable)
    - Duration tracking (for appointment scheduling)
    - Material references (placeholder for future inventory)
    - Odontogram integration (visual treatment mapping)
    """

    manifest = {
        "name": "catalog",
        "version": "0.1.0",
        "summary": "Treatment catalog, categories, VAT types.",
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": [],
        "installable": True,
        "auto_install": True,
        "removable": False,
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
                    "label": "nav.treatments",
                    "icon": "i-lucide-clipboard-list",
                    "to": "/treatments",
                    # `catalog.read` is the widest permission in the section:
                    # every role has it, and the landing page routes each one
                    # to a surface they can actually open.
                    "permission": "catalog.read",
                    # Keeps the slot the plan pipeline used to hold — the
                    # section leads with it, so the menu order should not move
                    # under people who use it daily.
                    "order": 30,
                },
            ],
        },
    }

    def get_models(self) -> list:
        return [TreatmentCategory, TreatmentCatalogItem, TreatmentOdontogramMapping, Specialty]

    def get_router(self) -> APIRouter:
        return router

    def get_providers(self) -> dict[type, object]:
        from app.core.contracts import ReferenceSpecialties, TreatmentCatalogue

        from .providers import specialties, treatments

        return {ReferenceSpecialties: specialties, TreatmentCatalogue: treatments}

    def get_event_handlers(self) -> dict:
        from .events import on_clinic_created, on_clinic_specialties_set

        return {
            "clinic.created": on_clinic_created,
            "clinic.specialties_set": on_clinic_specialties_set,
        }

    def get_permissions(self) -> list[str]:
        return [
            "read",  # View catalog items
            "write",  # Create/update catalog items
            "admin",  # Manage categories, bulk operations
        ]

    def get_tools(self) -> list:
        from .tools import get_tools

        return get_tools()
