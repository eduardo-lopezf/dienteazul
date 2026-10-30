"""Reports module - centralized reporting across all domains."""

from fastapi import APIRouter

from app.core.plugins import BaseModule
from app.core.scheduling import ScheduledJob

from .router import router


class ReportsModule(BaseModule):
    """Reports module providing unified reporting across budgets, scheduling, and billing.

    Features:
    - Billing reports (revenue, payments, VAT, overdue)
    - Budget reports (coming soon)
    - Scheduling reports (coming soon)
    - Export functionality (CSV)
    """

    manifest = {
        "name": "reports",
        # 0.2.0 added the module's first table (the scheduled-summary
        # standing order); 0.3.0 adds the monthly targets.
        "version": "0.4.0",
        "summary": "Cross-module reporting: billing, budgets, scheduling.",
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": [],
        # ADR 0037: each section answers only while its App runs
        # (integrations.py); with Patients or Professionals off, no names.
        "integrates": [
            "patients",
            "agenda",
            "catalog",
            "budget",
            "billing",
            "payments",
            "professionals",
        ],
        "egress": [
            {
                "target": "smtp",
                "subprocessor": (
                    "El servidor SMTP que configure cada clínica — el "
                    "destinatario real depende de esa configuración y no de "
                    "este código, así que el contrato lo firma la clínica."
                ),
                "residency": "unspecified",
                "data_classes": ["identifier", "operational", "financial"],
                "purpose": (
                    "Enviar a la propia clínica su resumen de una página "
                    "cuando lo programa. Salen las direcciones del personal "
                    "que lo recibe y las cifras agregadas del periodo; nunca "
                    "datos de un paciente identificable."
                ),
                "required": False,
            }
        ],
        "installable": True,
        "auto_install": True,
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["billing.read", "scheduling.read"],
            "hygienist": ["scheduling.read"],
            "assistant": ["scheduling.read"],
            "receptionist": ["billing.read", "scheduling.read"],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [
                {
                    "label": "nav.reports",
                    "icon": "i-lucide-bar-chart-3",
                    "to": "/reports",
                    "permission": "reports.billing.read",
                    "order": 60,
                },
            ],
        },
    }

    def get_models(self) -> list:
        # Every figure is computed on demand from other modules' tables.
        # The one row this module owns is the standing order for the
        # scheduled summary.
        from .models import MonthlyTarget, SummarySchedule

        return [SummarySchedule, MonthlyTarget]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return [
            "billing.read",  # View billing reports
            "budgets.read",  # View budget reports
            "scheduling.read",  # View scheduling reports
            "summary.read",  # Print the clinic's one-page summary
            "summary.write",  # Decide when the summary goes out, and to whom
            "actionable.read",  # Work the lists of patients to contact
        ]

    def get_scheduled_jobs(self) -> list[ScheduledJob]:
        from .tasks import send_scheduled_summaries

        return [
            ScheduledJob(
                id="send_scheduled_summaries",
                func=send_scheduled_summaries,
                trigger="cron",
                trigger_args={"hour": 7, "minute": 30},
                name=(
                    "Mail each clinic its one-page summary when a period closes "
                    "(daily 07:30; weekly on Monday, monthly on the 1st)"
                ),
            )
        ]

    def get_tools(self) -> list:
        from . import tools

        return tools.get_tools()
