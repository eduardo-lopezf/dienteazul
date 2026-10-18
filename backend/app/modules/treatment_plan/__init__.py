"""Treatment plan module - orchestrates patient treatment workflows.

This module provides:
- Treatment plan creation and management
- Integration with odontogram treatments (ToothTreatment)
- Budget synchronization via event bus
- Appointment treatment tracking
- Media attachments for before/after documentation
"""

from typing import Any

from fastapi import APIRouter

from app.core.events.types import EventType
from app.core.plugins import BaseModule
from app.core.scheduling import ScheduledJob

from .models import (
    PlannedTreatmentItem,
    PlanTemplate,
    PlanTemplateItem,
    TreatmentPlan,
    TreatmentPlanHistory,
    TreatmentPrescription,
)
from .owner_resolvers import register as _register_attachment_owners
from .router import router

# Register the ``plan_item`` attachment owner_type with media at import
# time. Safe because ``media`` is in ``manifest.depends`` and Python
# import order resolves it first.
_register_attachment_owners()


class TreatmentPlanModule(BaseModule):
    """Treatment plan module for orchestrating patient treatment workflows.

    Features:
    - Treatment plan CRUD with status workflow
    - Integration with ToothTreatment (odontogram)
    - Budget generation and synchronization
    - Event-driven communication with other modules
    - Media attachments for treatment documentation
    """

    manifest = {
        "name": "treatment_plan",
        "version": "0.1.0",
        "summary": "Patient treatment plans with budget + odontogram sync.",
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["patients", "odontogram", "catalog"],
        # Optional (ADR 0037), and none is imported (ADR 0039):
        # - `budget` prices a plan by reacting to what the plan announces
        #   (ADR 0042); the plan only asks it questions (`PlanBudgets`).
        #   With it off a confirmed plan goes straight to `active`.
        # - `payments` is asked one thing (`Collections`): whether the
        #   patient paid into a plan about to be deleted or cancelled.
        # - `professionals` is the directory a plan or a treatment is
        #   assigned to (`ProfessionalDirectory`). With it off nobody is
        #   assigned and no prescription can be issued.
        # - `agenda` tells the plan which treatments a visit covered, in
        #   `appointment.completed`. With it off plans advance by hand.
        # - `media` reads the attachment owner this module registers in
        #   `app.core.attachments`.
        "integrates": ["budget", "payments", "professionals", "agenda", "media"],
        "installable": True,
        "auto_install": True,
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["*"],
            "hygienist": ["plans.read", "prescriptions.read"],
            "assistant": [
                "plans.read",
                "plans.write",
                "prescriptions.read",
            ],
            # Reception drives the bandeja de planes: read + write notes
            # + close (terminal transitions tied to patient outcomes) +
            # reactivate (welcoming a returning patient back to draft).
            # Confirm stays with the doctor.
            "receptionist": [
                "plans.read",
                "plans.write",
                "plans.close",
                "plans.reactivate",
                # Reprinting a prescription the doctor already wrote.
                "prescriptions.read",
            ],
        },
        "frontend": {
            "layer_path": "frontend",
            # No navigation entry of its own: the plan pipeline lives under
            # the "Tratamientos" section owned by `catalog`, reached at
            # /treatments/plans. One menu entry, two surfaces — see the
            # section sub-nav in the catalog layer.
        },
    }

    def get_models(self) -> list:
        return [
            TreatmentPlan,
            PlannedTreatmentItem,
            PlanTemplate,
            PlanTemplateItem,
            TreatmentPlanHistory,
            TreatmentPrescription,
        ]

    def get_providers(self) -> dict[type, object]:
        from app.core.contracts import PlannedTreatments, PlanQuotes, ProfessionalWorkload

        from .providers import plan_quotes, planned_treatments, workload

        return {
            PlannedTreatments: planned_treatments,
            PlanQuotes: plan_quotes,
            ProfessionalWorkload: workload,
        }

    def get_router(self) -> APIRouter:
        return router

    def get_record_sections(self) -> list:
        from . import record

        return record.get_record_sections()

    def get_subject_contributors(self) -> list:
        from . import privacy

        return privacy.get_subject_contributors()

    def get_scheduled_jobs(self) -> list[ScheduledJob]:
        from .tasks import auto_close_expired_plans

        return [
            ScheduledJob(
                id="auto_close_expired_plans",
                func=auto_close_expired_plans,
                trigger="cron",
                trigger_args={"hour": 3, "minute": 0},
                name="Close pending plans whose budgets have been expired > N days (daily 03:00)",
            ),
        ]

    def get_permissions(self) -> list[str]:
        return [
            "plans.read",
            "plans.write",
            # Workflow transitions split out for fine-grained RBAC.
            "plans.confirm",
            "plans.close",
            "plans.reactivate",
            # Curating the clinic's plan templates. Reading them only needs
            # plans.read — everyone who builds a plan needs to see them.
            "plans.templates",
            # Prescriptions written from a treatment. Writing one is a
            # clinical act; reading (and reprinting) is not.
            "prescriptions.read",
            "prescriptions.write",
        ]

    def get_event_handlers(self) -> dict[str, Any]:
        from .events import (
            on_appointment_completed,
            on_budget_accepted,
            on_budget_created_for_plan,
            on_budget_rejected,
            on_budget_renegotiated,
            on_clinic_created,
            on_specialty_disabled,
            on_specialty_enabled,
            on_specialty_restored,
            on_treatment_performed,
        )

        return {
            EventType.CLINIC_CREATED: on_clinic_created,
            EventType.CATALOG_SPECIALTY_ENABLED: on_specialty_enabled,
            EventType.CATALOG_SPECIALTY_DISABLED: on_specialty_disabled,
            EventType.CATALOG_SPECIALTY_RESTORED: on_specialty_restored,
            EventType.APPOINTMENT_COMPLETED: on_appointment_completed,
            EventType.BUDGET_CREATED_FOR_PLAN: on_budget_created_for_plan,
            EventType.BUDGET_ACCEPTED: on_budget_accepted,
            EventType.BUDGET_REJECTED: on_budget_rejected,
            EventType.BUDGET_RENEGOTIATED: on_budget_renegotiated,
            EventType.ODONTOGRAM_TREATMENT_PERFORMED: on_treatment_performed,
        }
