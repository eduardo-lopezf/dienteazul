"""Payments module — patient-centric collections, allocations, refunds.

Owns the full payment lifecycle outside billing. A ``Payment`` belongs
to a patient and is split across one or more ``PaymentAllocation``
rows (target ``budget`` or ``on_account``). The link between a payment
and an invoice lives in the billing module (``InvoicePayment``) — that
direction respects the dependency graph (``billing.depends`` includes
``payments``; the reverse is forbidden).

The "earned" signal that powers patient-credit / receivable metrics
is computed from a denormalized ledger ``PatientEarnedEntry``,
populated by event handlers reacting to ``odontogram.treatment.performed``
and ``treatment_plan.treatment_completed``. No imports of those modules.

Refunds are first-class — there is no ``is_voided`` flag. A full reverso
is just ``Refund(amount=Payment.amount)``.
"""

from fastapi import APIRouter

from app.core.events import EventType
from app.core.plugins import BaseModule

from .events import on_session_completed, on_session_reopened, on_treatment_performed
from .models import (
    CollectionContact,
    PatientEarnedEntry,
    Payment,
    PaymentAllocation,
    PaymentHistory,
    PaymentSchedule,
    PaymentScheduleInstalment,
    Refund,
)
from .router import router


class PaymentsModule(BaseModule):
    manifest = {
        "name": "payments",
        "version": "0.1.0",
        "summary": (
            "Patient-centric collections, allocations to budgets / on-account, "
            "refunds, patient ledger, and dental payment reports."
        ),
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["budget"],
        # ADR 0037: runs with Patients off, reading only (budget/integrations.py).
        "integrates": ["patients"],
        "installable": True,
        "auto_install": True,
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["record.read", "record.write", "record.refund", "reports.read"],
            # Clinical-only roles don't see payment reports — they touch the
            # ledger from the patient screen, not from the dashboards.
            "hygienist": ["record.read"],
            "assistant": ["record.read", "record.write"],
            "receptionist": ["record.read", "record.write", "reports.read"],
        },
        "frontend": {
            "layer_path": "frontend",
            # Contributes the shared "Finanzas" entry rather than one of
            # its own: Cobros, Presupuestos and Facturas are tabs of a
            # single host page. All three modules declare the identical
            # entry and the sidebar de-duplicates by `to`, so the entry
            # survives while *any* of them is installed and disappears
            # when the last one goes. Declared here, not in the host,
            # because only the manifest is known during SSR — the tabs
            # themselves register client-side through `finance.tabs`.
            "navigation": [
                {
                    "label": "nav.finance",
                    "icon": "i-lucide-receipt",
                    "to": "/finanzas",
                    "permission": "payments.record.read",
                    "order": 46,
                },
            ],
        },
    }

    def get_models(self) -> list:
        return [
            Payment,
            PaymentAllocation,
            Refund,
            PatientEarnedEntry,
            PaymentHistory,
            PaymentSchedule,
            PaymentScheduleInstalment,
            CollectionContact,
        ]

    def get_router(self) -> APIRouter:
        return router

    def get_subject_contributors(self) -> list:
        from . import privacy

        return privacy.get_subject_contributors()

    def get_permissions(self) -> list[str]:
        return ["record.read", "record.write", "record.refund", "reports.read"]

    def get_providers(self) -> dict[type, object]:
        from app.core.contracts import Collections

        from .providers import collections

        return {Collections: collections}

    def get_tools(self) -> list:
        from . import tools

        return tools.get_tools()

    def get_event_handlers(self) -> dict:
        return {
            EventType.ODONTOGRAM_TREATMENT_PERFORMED: on_treatment_performed,
            # Per-session earned signal (multi-session billing).
            # Single-session items publish this once too — the legacy
            # ``treatment_plan.treatment_completed`` handler was removed
            # to avoid double-booking the same treatment.
            EventType.TREATMENT_PLAN_ITEM_SESSION_COMPLETED: on_session_completed,
            # Its reverse: a completion undone drops the charge it booked.
            EventType.TREATMENT_PLAN_ITEM_SESSION_REOPENED: on_session_reopened,
        }
