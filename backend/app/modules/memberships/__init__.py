"""Memberships module — plans a clinic signs its patients up to.

A plan has a fee per period (monthly or annual), included services
(N units of a catalogue treatment per membership year) and discounts. A
patient's membership is in force while a fee covers the day, plus a few
days' grace. The fee is collected as a payment of the patient in the
Budgets and payments App (``MembershipFees``); budgets suggest the
member's discount on new lines and payments book performed treatments at
what the member pays (``MemberBenefits``).

An optional module of the Patients App: off for each clinic until its
administrator switches it on from Settings → Apps → Pacientes →
Configurar, and only a clinic (``account_tier = clinic``) may (ADR 0066).
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import (
    MembershipBenefitUsage,
    MembershipPeriod,
    MembershipPlan,
    MembershipPlanBenefit,
    PatientMembership,
)
from .router import router


class MembershipsModule(BaseModule):
    manifest = {
        "name": "memberships",
        "version": "0.1.0",
        "summary": "Membresías: planes de la clínica a los que se suscribe a los pacientes.",
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["patients"],
        "installable": True,
        # Runs for every deployment so each clinic has something to switch
        # on from the Patients App's settings (`optional_modules` in
        # apps.json, ADR 0066).
        "auto_install": True,
        # Switched off with `disable` (ADR 0035); the fees are payments.
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["plan.read", "membership.read"],
            "hygienist": ["membership.read"],
            "assistant": ["plan.read", "membership.read"],
            "receptionist": ["plan.read", "membership.read", "membership.write"],
        },
        "frontend": {
            "layer_path": "frontend",
            # A tab on the patient record (`patient.detail.tabs`) and the plans
            # page, reached from the Patients App's card in Settings → Apps.
            "navigation": [],
        },
    }

    def get_models(self) -> list:
        return [
            MembershipPlan,
            MembershipPlanBenefit,
            PatientMembership,
            MembershipPeriod,
            MembershipBenefitUsage,
        ]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["plan.read", "plan.write", "membership.read", "membership.write"]

    def get_providers(self) -> dict[type, object]:
        from app.core.contracts import MemberBenefits

        from .providers import member_benefits

        return {MemberBenefits: member_benefits}

    def get_event_handlers(self) -> dict:
        from app.core.events import EventType

        from .events import on_payment_refunded

        return {EventType.PAYMENT_REFUNDED: on_payment_refunded}

    def get_subject_contributors(self) -> list:
        from . import privacy

        return privacy.get_subject_contributors()

    def get_tools(self) -> list:
        from . import tools

        return tools.get_tools()
