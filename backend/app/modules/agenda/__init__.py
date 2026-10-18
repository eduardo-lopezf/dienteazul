"""Agenda module — appointments + scheduling + cabinets."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import (
    Appointment,
    AppointmentCabinetEvent,
    AppointmentStatusEvent,
    AppointmentTreatment,
    Cabinet,
)
from .router import router


class AgendaModule(BaseModule):
    """Scheduling module: appointments, appointment treatments, cabinets."""

    manifest = {
        "name": "agenda",
        "version": "0.4.0",
        "summary": "Appointments, scheduling, cabinets.",
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        # Nothing is required: the agenda books an appointment with no
        # patient, no professional and no treatments (ADR 0037).
        "depends": [],
        # Linked when they run, done without when they do not. The agenda
        # imports none of them — it reaches them through the core
        # contracts (ADR 0039) — so this lists only the owners of tables
        # its foreign keys point at. `schedules` and `odontogram` are
        # reached through contracts alone and need no entry.
        "integrates": ["patients", "professionals", "catalog", "treatment_plan"],
        "installable": True,
        "auto_install": True,
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["*"],
            "hygienist": [
                "appointments.read",
                "appointments.write",
                "cabinets.read",
            ],
            "assistant": [
                "appointments.read",
                "appointments.write",
                "cabinets.read",
            ],
            "receptionist": [
                "appointments.read",
                "appointments.write",
                "cabinets.read",
            ],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [
                {
                    "label": "nav.appointments",
                    "icon": "i-lucide-calendar",
                    "to": "/appointments",
                    "permission": "agenda.appointments.read",
                    "order": 20,
                },
            ],
        },
    }

    def get_models(self) -> list:
        return [
            Cabinet,
            Appointment,
            AppointmentTreatment,
            AppointmentStatusEvent,
            AppointmentCabinetEvent,
        ]

    def get_providers(self) -> dict[type, object]:
        from app.core.contracts import AppointmentBook, ProfessionalWorkload

        from .providers import appointment_book, workload

        return {AppointmentBook: appointment_book, ProfessionalWorkload: workload}

    def get_router(self) -> APIRouter:
        return router

    def get_subject_contributors(self) -> list:
        from . import privacy

        return privacy.get_subject_contributors()

    def get_permissions(self) -> list[str]:
        return [
            "appointments.read",
            "appointments.write",
            "cabinets.read",
            "cabinets.write",
        ]

    def get_tools(self) -> list:
        from . import tools

        return tools.get_tools()
