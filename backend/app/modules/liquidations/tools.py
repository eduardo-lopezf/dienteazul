"""Agent tools for the liquidations module.

Read only. What an associate is owed is a number a person hands over and
stands behind; issuing the document is that act, and an agent cannot make
it. Answering "what do I owe María this quincena" is useful and safe.
"""

from __future__ import annotations

from datetime import date as date_cls
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.agents import AgentContext, Tool, ToolCategory
from app.core.auth.models import Clinic

from .service import APPS_UNAVAILABLE, LiquidationService, can_calculate


class PreviewArgs(BaseModel):
    professional_id: UUID = Field(description="Id del profesional a liquidar.")
    date_from: date_cls = Field(description="Inicio del periodo (YYYY-MM-DD).")
    date_to: date_cls = Field(description="Fin del periodo (YYYY-MM-DD).")


async def _liquidation_preview(ctx: AgentContext, args: PreviewArgs) -> dict:
    if not can_calculate():
        return {"error": "apps_unavailable", "detail": APPS_UNAVAILABLE}
    clinic = await ctx.db.scalar(select(Clinic).where(Clinic.id == ctx.clinic_id))
    preview = await LiquidationService.preview(
        ctx.db,
        ctx.clinic_id,
        clinic.currency if clinic else "MXN",
        clinic.timezone if clinic else "UTC",
        args.professional_id,
        args.date_from,
        args.date_to,
    )
    # The per-treatment detail is dropped: the agent gets the shape of the
    # settlement, and the screen is where the lines are read.
    return preview.model_dump(exclude={"lines"})


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="liquidation_preview",
            description=(
                "Liquidación de un profesional asociado en un periodo: lo "
                "devengado (trabajo hecho), lo cobrado de ese trabajo, y el "
                "porcentaje acordado sobre uno de los dos. Los dos números "
                "son distintos y la diferencia importa: pagar sobre lo "
                "devengado reparte dinero que la clínica todavía no ha "
                "recibido."
            ),
            parameters=PreviewArgs,
            handler=_liquidation_preview,
            permissions=["liquidations.settlement.read"],
            category=ToolCategory.READ,
        ),
    ]
