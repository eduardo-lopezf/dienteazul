"""Agent tools for the inventory module.

Read only, and that is a decision rather than a stage of work. Recording
a movement is a claim about the physical world — someone took a box off a
shelf — and an agent has no way to witness it. What an agent can usefully
do is answer "what are we about to run out of", which is a question the
clinic currently cannot ask at all.

Thin wrappers over the services; no logic duplicated, every handler
scoped by ``ctx.clinic_id`` exactly as the routers are.
"""

from __future__ import annotations

from datetime import date as date_cls

from pydantic import BaseModel, Field

from app.core.agents import AgentContext, Tool, ToolCategory

from .schemas import ItemCategory, MovementReason
from .service import EXPIRY_WINDOW_DAYS, StockService


class StockArgs(BaseModel):
    search: str | None = Field(
        default=None, description="Texto a buscar en el nombre o el código del artículo."
    )
    category: ItemCategory | None = Field(default=None, description="Categoría de artículo.")
    only_low: bool = Field(
        default=False, description="Solo los artículos en o por debajo de su punto de pedido."
    )


class AlertsArgs(BaseModel):
    window_days: int = Field(
        default=EXPIRY_WINDOW_DAYS,
        ge=1,
        le=365,
        description="Cuántos días vista cuentan como 'caduca pronto'.",
    )


class LedgerArgs(BaseModel):
    date_from: date_cls = Field(description="Inicio del periodo (YYYY-MM-DD).")
    date_to: date_cls = Field(description="Fin del periodo (YYYY-MM-DD).")
    reason: MovementReason | None = Field(
        default=None, description="Filtrar por motivo del movimiento."
    )


def _line(line: dict) -> dict:
    """One stock row, with native values: `jsonify` coerces at the registry."""
    return {
        "item_code": line["item_code"],
        "item_name": line["item_name"],
        "category": line["category"],
        "location_name": line["location_name"],
        "lot_code": line["lot_code"],
        "expires_on": line["expires_on"],
        "days_to_expiry": line["days_to_expiry"],
        "quantity": line["quantity"],
        "base_unit": line["base_unit"],
        "item_total": line["item_total"],
        "reorder_point": line["reorder_point"],
        "is_low": line["is_low"],
    }


async def _inventory_stock(ctx: AgentContext, args: StockArgs) -> list[dict]:
    lines = await StockService.levels(
        ctx.db, ctx.clinic_id, category=args.category, search=args.search
    )
    return [_line(line) for line in lines if not args.only_low or line["is_low"]]


async def _inventory_alerts(ctx: AgentContext, args: AlertsArgs) -> dict:
    alerts = await StockService.alerts(ctx.db, ctx.clinic_id, window_days=args.window_days)
    return {key: [_line(line) for line in lines] for key, lines in alerts.items()}


async def _inventory_movements(ctx: AgentContext, args: LedgerArgs) -> list[dict]:
    movements, _total = await StockService.movements(
        ctx.db,
        ctx.clinic_id,
        page=1,
        page_size=100,
        reason=args.reason,
        date_from=args.date_from,
        date_to=args.date_to,
    )
    return [
        {
            "recorded_at": m.created_at,
            "item_name": m.item.name,
            "location_name": m.location.name,
            "lot_code": m.lot.lot_code if m.lot else None,
            "quantity_base": m.quantity_base,
            "base_unit": m.item.base_unit,
            "reason": m.reason,
            "note": m.note,
        }
        for m in movements
    ]


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="inventory_stock",
            description=(
                "Existencias de material de la clínica: cuánto hay de cada "
                "artículo, en qué ubicación y de qué lote, con el total del "
                "artículo y si está en su punto de pedido."
            ),
            parameters=StockArgs,
            handler=_inventory_stock,
            permissions=["inventory.stock.read"],
            category=ToolCategory.READ,
        ),
        Tool(
            name="inventory_alerts",
            description=(
                "Qué hay que mirar del almacén: artículos que se están "
                "acabando, lotes que caducan pronto y lotes ya caducados que "
                "siguen contando como existencias."
            ),
            parameters=AlertsArgs,
            handler=_inventory_alerts,
            permissions=["inventory.stock.read"],
            category=ToolCategory.READ,
        ),
        Tool(
            name="inventory_movements",
            description=(
                "Movimientos de almacén de un periodo: qué entró, qué se "
                "gastó, qué se tiró y qué ajustes se hicieron, con su motivo. "
                "Es el libro: explica por qué las existencias son las que son."
            ),
            parameters=LedgerArgs,
            handler=_inventory_movements,
            permissions=["inventory.stock.read"],
            category=ToolCategory.READ,
            # `note` is whatever the person who posted the movement typed.
            exposes_free_text=True,
        ),
    ]
