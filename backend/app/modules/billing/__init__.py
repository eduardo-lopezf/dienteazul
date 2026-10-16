"""Billing module - invoice management and payment tracking."""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import Invoice, InvoiceHistory, InvoiceItem, InvoicePayment, InvoiceSeries
from .router import router


class BillingModule(BaseModule):
    """Billing module providing invoice management and payment tracking.

    Features:
    - Invoice creation from budgets or manual
    - Partial invoicing support
    - Multiple payment methods
    - Credit notes (rectificativas)
    - Invoice series with numbering control
    - PDF generation
    - Extensible hooks for country compliance modules
    """

    manifest = {
        "name": "billing",
        "version": "0.1.0",
        "summary": "Invoices, payments, credit notes, PDF billing.",
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["budget", "payments"],
        # ADR 0037: runs with these off (budget/integrations.py).
        "integrates": ["patients", "catalog"],
        "installable": True,
        "auto_install": True,
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            "dentist": ["*"],
            "hygienist": ["read"],
            "assistant": ["read", "write"],
            "receptionist": ["read", "write"],
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
                    "permission": "billing.read",
                    "order": 46,
                },
            ],
        },
    }

    def get_models(self) -> list:
        return [InvoiceSeries, Invoice, InvoiceItem, InvoicePayment, InvoiceHistory]

    def get_tools(self) -> list:
        from . import tools

        return tools.get_tools()

    def get_router(self) -> APIRouter:
        return router

    def get_subject_contributors(self) -> list:
        from . import privacy

        return privacy.get_subject_contributors()

    def get_permissions(self) -> list[str]:
        return [
            "read",  # View invoices
            "write",  # Create/update invoices, record payments
            "admin",  # Manage series, settings, void invoices
        ]

    def get_event_handlers(self) -> dict:
        # ``budget.completed`` was never actually published; the handler
        # was orphaned. Removed alongside the ``BudgetWorkflowService.complete_budget``
        # path. Re-add a subscription here when invoices need to react
        # to budget lifecycle events again.
        from app.core.events import EventType

        from .events import on_payment_refunded

        return {
            # When a Payment is refunded, recompute affected invoices'
            # status so paid → partial / partial → issued transitions
            # happen without billing owning the payment row.
            EventType.PAYMENT_REFUNDED: on_payment_refunded,
        }
