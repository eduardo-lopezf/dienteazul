"""Agent tools for the purchasing module.

One, and read only. "What did we order and when is it due" is a question
the clinic asks constantly and cannot currently ask at all; placing an
order is a commitment to spend money with a named supplier, which is not
an agent's to make.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.agents import AgentContext, Tool, ToolCategory

from .service import OrderService


class OpenOrdersArgs(BaseModel):
    open_only: bool = Field(
        default=True,
        description="Solo pedidos pendientes de recibir. False incluye los cerrados.",
    )


async def _purchase_orders(ctx: AgentContext, args: OpenOrdersArgs) -> list[dict]:
    orders = await OrderService.list(ctx.db, ctx.clinic_id, open_only=args.open_only)
    return [
        {
            "number": order.number,
            "status": order.status,
            # The supplier's own name, under the column's name, so the
            # redactor tokenizes it on the cloud path (ADR 0025).
            "name": order.supplier.name,
            "order_date": order.order_date,
            "expected_date": order.expected_date,
            "lines": [
                {
                    "item_name": line.item.name,
                    "base_unit": line.item.base_unit,
                    "quantity_ordered": line.quantity_ordered,
                    "quantity_received": line.quantity_received,
                }
                for line in order.lines
            ],
        }
        for order in orders
    ]


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="purchase_orders",
            description=(
                "Pedidos a proveedores: qué se pidió, a quién, cuándo se "
                "espera y qué falta por llegar de cada línea."
            ),
            parameters=OpenOrdersArgs,
            handler=_purchase_orders,
            permissions=["purchasing.orders.read"],
            category=ToolCategory.READ,
        )
    ]
