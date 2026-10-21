"""The pediatric health questionnaire (odontología pediátrica).

``form_kind`` says which form was answered — every existing row was the
adult one — and ``form_data`` holds what the pediatric form asks to write
rather than answer yes or no (school, guardian, weight…).

Revision ID: pc_0008
Revises: pc_0007
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "pc_0008"
down_revision: str | None = "pc_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "patients_clinical_health_questionnaire"


def upgrade() -> None:
    op.add_column(
        _TABLE, sa.Column("form_kind", sa.String(20), server_default="adult", nullable=False)
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "form_data", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_health_questionnaire_form_kind", _TABLE, "form_kind IN ('adult', 'pediatric')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_health_questionnaire_form_kind", _TABLE, type_="check")
    op.drop_column(_TABLE, "form_data")
    op.drop_column(_TABLE, "form_kind")
