"""The patient's signature on a health questionnaire answered on screen.

Who signed, in what capacity, when, the drawing, and the regulation the
form named that day.

Revision ID: pc_0007
Revises: pc_0006
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "pc_0007"
down_revision: str | None = "pc_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "patients_clinical_health_questionnaire"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(_TABLE, sa.Column("signed_by_name", sa.String(200), nullable=True))
    op.add_column(_TABLE, sa.Column("signer_capacity", sa.String(20), nullable=True))
    op.add_column(_TABLE, sa.Column("signature_data", postgresql.JSONB(), nullable=True))
    op.add_column(_TABLE, sa.Column("regulation", sa.String(300), nullable=True))


def downgrade() -> None:
    for column in (
        "regulation",
        "signature_data",
        "signer_capacity",
        "signed_by_name",
        "signed_at",
    ):
        op.drop_column(_TABLE, column)
