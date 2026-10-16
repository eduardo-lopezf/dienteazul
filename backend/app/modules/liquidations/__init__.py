"""Liquidations module — settling with associate dentists.

An associate on a percentage is paid from one of two numbers, and they are
not the same number: what they **earned** (the work they performed, priced)
and what has been **collected** for it (what the patient actually paid). On
a large case those are months apart, and paying a percentage of the first
means the clinic hands out money it has not received.

Most Mexican clinics pay on the second, so `collected` is the default —
but both are computed and both are shown, because neither can be judged
without the other. Which one a given professional is paid on is an
arrangement the clinic records per person.

Depends on `payments` for the earned ledger and the FIFO coverage walk that
attributes collected money to the work it paid for, on `professionals` for
who is being settled with, and on `cashbox` — which is the one it writes to:
paying a settlement in cash empties the drawer, and the payout and the till
movement are one fact seen twice.
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import Liquidation, ProfessionalCommission
from .router import router


class LiquidationsModule(BaseModule):
    manifest = {
        "name": "liquidations",
        "version": "0.1.0",
        "summary": (
            "Liquidación a profesionales asociados: lo devengado, lo cobrado "
            "y el porcentaje acordado sobre uno de los dos."
        ),
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["cashbox"],
        # ADR 0037: with either off, issued settlements are read and paid and
        # no new one is calculated (`service.can_calculate`).
        "integrates": ["payments", "professionals"],
        "installable": True,
        # Not every clinic has associates on a percentage, and the ones that
        # do not should not carry the screen. Opt in.
        "auto_install": False,
        # An issued settlement is what somebody was paid on. Fiscal
        # retention forbids dropping it, same as `payments` and `cashbox`.
        "removable": False,
        "role_permissions": {
            "admin": ["*"],
            # A dentist can see what they are owed; the percentage itself is
            # the owner's business, and issuing is too.
            "dentist": ["settlement.read"],
        },
        "frontend": {
            "layer_path": "frontend",
            # A tab of the shared Finanzas page, registered client-side
            # through `finance.tabs`. No navigation entry of its own.
            "navigation": [],
        },
    }

    def get_models(self) -> list:
        return [ProfessionalCommission, Liquidation]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return ["settlement.read", "settlement.issue", "commission.write"]

    def get_tools(self) -> list:
        from . import tools

        return tools.get_tools()
