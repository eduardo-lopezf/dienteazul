"""Commissions module — what each professional is paid, treatment by treatment.

A general percentage per professional and, optionally, a different one for
specific treatments of the catalogue (40 % in general, 50 % on implants).
Configured from the professional's card in the Professionals App; read by
`liquidations` through the core ``CommissionRates`` contract, so the
settlement takes each treatment at its own percentage. An optional module
of its App: off for each clinic until switched on (ADR 0066).
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import CommissionAgreement, CommissionRate
from .router import router


class CommissionsModule(BaseModule):
    manifest = {
        "name": "commissions",
        "version": "0.1.0",
        "summary": (
            "Comisiones por profesional: un porcentaje general y, si hace falta, "
            "uno distinto por tratamiento del catálogo."
        ),
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["professionals"],
        "installable": True,
        # Runs for every deployment; each clinic switches it on from the
        # Professionals App's settings (`optional_modules` in apps.json,
        # ADR 0066). Not every clinic pays its professionals a share.
        "auto_install": True,
        # Switched off with `disable` (ADR 0035); dropping the agreements
        # gains nothing, and issued liquidations keep their own copy.
        "removable": False,
        "role_permissions": {
            # What a clinic pays its professionals is the owner's business.
            "admin": ["*"],
        },
        "frontend": {
            "layer_path": "frontend",
            # A button on the professional's card (`professional.profile.actions`),
            # no navigation entry of its own.
            "navigation": [],
        },
    }

    def get_models(self) -> list:
        return [CommissionAgreement, CommissionRate]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["agreement.read", "agreement.write"]

    def get_providers(self) -> dict[type, object]:
        from app.core.contracts import CommissionRates

        from .providers import commission_rates

        return {CommissionRates: commission_rates}

    def get_event_handlers(self) -> dict:
        from app.core.events import EventType

        from .events import on_clinic_module_enabled

        return {EventType.CLINIC_MODULE_ENABLED: on_clinic_module_enabled}

    def get_tools(self) -> list:
        # What a professional is paid is a number the owner sets and stands
        # behind; the outcome reaches agents through `liquidation_preview`.
        return []
