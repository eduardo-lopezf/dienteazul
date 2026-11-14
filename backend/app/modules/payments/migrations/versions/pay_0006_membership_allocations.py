"""payments — membership fees as an allocation target.

A membership fee (`memberships`, through the ``MembershipFees`` contract)
is a payment allocated to ``membership``, pointing at the period it paid
by ``membership_period_id`` — no foreign key, the module is another App's.

Revision ID: pay_0006
Revises: pay_0005
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "pay_0006"
down_revision: str | None = "pay_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_allocations",
        sa.Column("membership_period_id", sa.UUID(), nullable=True),
    )
    op.drop_constraint("ck_alloc_target_consistency", "payment_allocations", type_="check")
    op.create_check_constraint(
        "ck_alloc_target_consistency",
        "payment_allocations",
        "(target_type = 'budget' AND budget_id IS NOT NULL AND membership_period_id IS NULL) "
        "OR (target_type = 'on_account' AND budget_id IS NULL "
        "AND membership_period_id IS NULL) "
        "OR (target_type = 'membership' AND budget_id IS NULL "
        "AND membership_period_id IS NOT NULL)",
    )


def downgrade() -> None:
    # A membership allocation has no place in the old rule: the downgrade
    # refuses rather than rewrite what a fee paid for.
    op.drop_constraint("ck_alloc_target_consistency", "payment_allocations", type_="check")
    op.create_check_constraint(
        "ck_alloc_target_consistency",
        "payment_allocations",
        "(target_type = 'budget' AND budget_id IS NOT NULL) "
        "OR (target_type = 'on_account' AND budget_id IS NULL)",
    )
    op.drop_column("payment_allocations", "membership_period_id")
