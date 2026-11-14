"""Agent tools for the memberships module.

Thin wrappers over ``MembershipService`` — no business logic here.
Clinic-scoped; RBAC via ``memberships.membership.read``.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.core.agents import AgentContext, Tool, ToolCategory

from .service import MembershipService, covering_period, paid_through, state_on, today


class PatientArgs(BaseModel):
    patient_id: UUID


async def _membership_status(ctx: AgentContext, params: PatientArgs) -> dict:
    membership = await MembershipService.for_patient(ctx.db, ctx.clinic_id, params.patient_id)
    if membership is None:
        return {"patient_id": params.patient_id, "has_membership": False}
    on = today()
    covering = covering_period(membership, on)
    used = await MembershipService.used_in_cycle(ctx.db, membership, on)
    included = []
    if covering is not None:
        included = [
            {
                "catalog_item_id": UUID(b["catalog_item_id"]),
                "quantity": b["quantity"],
                "used": used.get(UUID(b["catalog_item_id"]), 0),
            }
            for b in covering.terms["benefits"]
            if b["kind"] == "included"
        ]
    return {
        "patient_id": params.patient_id,
        "has_membership": True,
        "plan_name": membership.plan.name,
        "state": state_on(membership, on),
        "paid_through": paid_through(membership),
        "included": included,
    }


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="membership_status",
            description=(
                "Membresía de un paciente: plan, estado (activa, vencida o cancelada), "
                "pagada hasta y servicios incluidos usados en el año de membresía."
            ),
            parameters=PatientArgs,
            handler=_membership_status,
            permissions=["memberships.membership.read"],
            category=ToolCategory.READ,
        ),
    ]
