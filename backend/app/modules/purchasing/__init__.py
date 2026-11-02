"""Purchasing module — suppliers, orders, and goods coming in.

Layer 2 of [`docs/features/inventory.md`](../../../../docs/features/inventory.md).
The inventory says what is on the shelf; this says what was ordered, from
whom, at what price, and what is still on its way.

**Receiving does not write stock.** It calls the inventory's
``StockService.post``, so a delivery becomes ordinary movements in the
ledger that is the only truth about stock (ADR 0065) — with the price
paid carried on each one, which is what makes real material cost
possible later.

The dependency runs one way: `inventory` knows nothing about purchase
orders, and would keep working untouched if this module were disabled.
Both live in the same App, so the import is what ``depends`` is for.
"""

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .models import PurchaseOrder, PurchaseOrderLine, Supplier
from .router import router


class PurchasingModule(BaseModule):
    manifest = {
        "name": "purchasing",
        "version": "0.1.0",
        "summary": (
            "Compras del almacén: proveedores, pedidos y recepción de mercancía, "
            "con el coste medio del artículo."
        ),
        "author": "Diente Azul Core Team",
        "license": "BSL-1.1",
        "category": "official",
        # Not optional: an order line points at an article and receiving
        # posts to the ledger. Without the inventory there is nothing to
        # order and nowhere to put it.
        "depends": ["inventory"],
        "integrates": [],
        "installable": True,
        # Follows the App it belongs to: a clinic that turns the
        # inventory on gets stock first and decides about purchasing.
        "auto_install": False,
        # Orders are not an accounting record — the invoice is, and that
        # is `billing`'s. A clinic that stops using purchase orders can
        # drop them.
        "removable": True,
        "role_permissions": {
            "admin": ["*"],
            # Reception is who takes the delivery from the courier, so
            # receiving is theirs. Ordering and supplier data are not.
            "receptionist": ["suppliers.read", "orders.read", "orders.receive"],
            "assistant": ["suppliers.read", "orders.read", "orders.receive"],
            "dentist": ["orders.read"],
            "hygienist": ["orders.read"],
        },
        "frontend": {
            "layer_path": "frontend",
            # No navigation entry of its own: Compras is reached from
            # Existencias, like the rest of the inventory's screens.
            "navigation": [],
        },
    }

    def get_models(self) -> list:
        return [Supplier, PurchaseOrder, PurchaseOrderLine]

    def get_router(self) -> APIRouter:
        return router

    def get_permissions(self) -> list[str]:
        return [
            "suppliers.read",
            "suppliers.write",
            "orders.read",
            "orders.write",
            # Separate from `orders.write` on purpose: whoever unpacks the
            # box says what arrived, which is not the same right as
            # committing the clinic to buy it.
            "orders.receive",
        ]

    def get_tools(self) -> list:
        from . import tools

        return tools.get_tools()
