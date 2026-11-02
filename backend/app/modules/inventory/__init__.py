"""Inventory module — what the clinic has on the shelf, and why.

A dental clinic spends real money on things that sit in a drawer and
expire, and until now nothing in Diente Azul knew they existed. This
module is the shelf: articles, where they are kept, the lots they came
in, and an append-only ledger of everything that moved.

The shape of it is one decision, recorded in
[ADR 0065](../../../../docs/adr/0065-stock-is-a-ledger-the-level-is-a-snapshot.md):
``inv_movements`` is the truth and ``inv_stock_levels`` is a snapshot
derived from it. That is what lets every number on screen be explained,
a physical count be reconciled instead of rescued, and real material
cost arrive later without a migration.

V1 is layers 0 and 1 of `docs/features/inventory.md`: stock, locations,
lots, expiry and reorder points. Purchasing, consumption driven by
treatments and implant traceability are designed there and not built.

It depends on nothing and imports no other module: stock control is
useful with Patients, Agenda and Treatments all switched off, which is
what makes this a genuinely optional App (ADR 0037) and keeps it
extractable later (ADR 0042).
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule
from app.core.scheduling import ScheduledJob

from .models import (
    ImplantTrace,
    InventoryItem,
    InventoryLocation,
    InventoryLot,
    InventoryMovement,
    InventoryStockLevel,
    TreatmentMaterial,
)
from .router import router


class InventoryModule(BaseModule):
    manifest = {
        "name": "inventory",
        "version": "0.1.0",
        "summary": (
            "Almacén de la clínica: artículos, ubicaciones, lotes con caducidad, "
            "movimientos de existencias y avisos de reposición."
        ),
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        # Nothing required, and nothing integrated in the sense
        # `integrates` means: that field lists the owners of tables this
        # module's foreign keys point at, and there are none. The links
        # to `catalog` and `treatment_plan` are contracts and an event
        # (`integrations.py`, `events.py`) — with those Apps off the
        # inventory keeps every figure it has (ADR 0037, ADR 0039).
        "depends": [],
        "integrates": [],
        "installable": True,
        # An optional App nobody asked for should not appear on its own.
        "auto_install": False,
        # Stock is not a legal record: a clinic that gives up on counting
        # material can drop the whole thing. The uninstall round-trip is
        # covered in `tests/test_inventory.py`.
        "removable": True,
        "role_permissions": {
            "admin": ["*"],
            # Whoever works clinically takes material off the shelf, so
            # they read stock and record what they used. Master data and
            # adjustments are administration's.
            # Whoever places a device records it; whoever assists or
            # answers a recall needs to read the traces.
            "dentist": [
                "stock.read",
                "stock.write",
                "items.read",
                "implants.read",
                "implants.write",
            ],
            "hygienist": ["stock.read", "stock.write", "items.read", "implants.read"],
            "assistant": ["stock.read", "stock.write", "items.read", "implants.read"],
            # Reception receives the supplier's delivery, and is who
            # phones the patients when a batch is withdrawn.
            "receptionist": ["stock.read", "stock.write", "items.read", "implants.read"],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [
                {
                    "label": "nav.inventory",
                    "icon": "i-lucide-package",
                    "to": "/inventario",
                    "permission": "inventory.stock.read",
                    # After Productividad (60) and before Configuración:
                    # the shelf is checked less often than the agenda or a
                    # patient, and more often than the catalogue.
                    "order": 65,
                },
            ],
        },
    }

    def get_providers(self) -> dict[type, object]:
        # The module's only outward contract, and the first thing that
        # flows out of it at all (ADR 0039). `reports` asks for it;
        # nothing imports this module.
        from app.core.contracts import MaterialCost

        from .providers import material_cost

        return {MaterialCost: material_cost}

    def get_subject_contributors(self) -> list:
        # One table here holds patient data: which batch of which device
        # a patient carries. It exports and refuses erasure, because
        # medical-device traceability outlives a deletion request
        # (ADR 0026).
        from .privacy import get_subject_contributors

        return get_subject_contributors()

    def get_event_handlers(self) -> dict:
        from .events import on_treatment_completed

        # Layer 3: the clinic finishes a treatment and what it is
        # expected to use leaves the shelf. `treatment_plan` announces a
        # fact about its own world and knows nothing about stock; with
        # this module off the event simply goes unanswered (ADR 0064).
        return {"treatment_plan.treatment_completed": on_treatment_completed}

    def get_models(self) -> list:
        return [
            InventoryItem,
            InventoryLocation,
            InventoryLot,
            InventoryMovement,
            InventoryStockLevel,
            TreatmentMaterial,
            ImplantTrace,
        ]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return [
            "stock.read",
            "stock.write",
            # Separate from `stock.write` on purpose: an adjustment is the
            # one action that can make the system agree with any number at
            # all, so it is not granted to whoever records a consumption.
            "stock.adjust",
            "items.read",
            "items.write",
            # Layer 4. Reading a trace is reading patient data, so it is
            # not folded into `stock.read`: most of the inventory is
            # about things, and this is the one part that is about
            # people.
            "implants.read",
            "implants.write",
        ]

    def get_tools(self) -> list:
        from . import tools

        return tools.get_tools()

    def get_scheduled_jobs(self) -> list[ScheduledJob]:
        from .tasks import announce_stock_alerts

        return [
            ScheduledJob(
                id="announce_stock_alerts",
                func=announce_stock_alerts,
                trigger="cron",
                trigger_args={"hour": 7, "minute": 30},
                name="Announce low stock and expiring lots (daily 07:30)",
            )
        ]
