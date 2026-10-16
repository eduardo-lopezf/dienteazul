"""Cashbox module — the clinic's till: movements, arqueo, and period cuts.

A *corte de caja* is not a report. The reports in `payments` already answer
"how much came in this week, by method, by professional". What a corte adds
is an **act**: someone counts the drawer, declares what was in it, and the
difference between that and what the system expected is frozen. The number
that matters is the one no query can produce.

Phase 1 ships the half that does not exist anywhere yet — the money that
leaves the till without being a patient payment. It is first because it is
useful alone ("where did today's cash go?") and because without it the
count can never match, the difference is non-zero every day, and the whole
feature gets abandoned as broken.

Depends on `payments` because the arqueo reads its cash collections and
refunds. It never writes there, and `payments` knows nothing about this
module.
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import CashClosing, CashMovement, LateEntryAck
from .router import router


class CashboxModule(BaseModule):
    manifest = {
        "name": "cashbox",
        "version": "0.1.0",
        "summary": (
            "Caja de la clínica: movimientos de efectivo, arqueo diario y cortes por periodo."
        ),
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": [],
        # ADR 0037: with Cobros off the till counts only its own movements.
        "integrates": ["payments"],
        "installable": True,
        "auto_install": True,
        # Same reason as `payments`: a cash count is an accounting record
        # and fiscal retention forbids dropping it. A clinic that never
        # handles cash carries an unused tab, which is cheaper than a
        # clinic that uninstalls and loses two years of arqueos.
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            "dentist": [
                "movement.read",
                "movement.write",
                "closing.read",
                "closing.write",
            ],
            # Reception is who actually opens the drawer, so they count and
            # they close. `closing.reopen` is not theirs: throwing away a
            # count somebody signed is administration's call.
            "receptionist": [
                "movement.read",
                "movement.write",
                "closing.read",
                "closing.write",
            ],
            "assistant": ["movement.read", "movement.write", "closing.read"],
            # Clinical-only role: no business at the till.
            "hygienist": [],
        },
        "frontend": {
            "layer_path": "frontend",
            # No navigation entry of its own: Caja is a tab of the shared
            # Finanzas page, registered client-side through `finance.tabs`.
            # The sidebar entry belongs to whichever finance module is
            # installed and is de-duplicated by `to`.
            "navigation": [],
        },
    }

    def get_models(self) -> list:
        return [CashClosing, CashMovement, LateEntryAck]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return [
            "movement.read",
            "movement.write",
            "closing.read",
            "closing.write",
            "closing.reopen",
        ]

    def get_tools(self) -> list:
        from . import tools

        return tools.get_tools()
