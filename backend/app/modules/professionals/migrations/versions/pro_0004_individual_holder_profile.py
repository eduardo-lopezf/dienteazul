"""The holder of an individual practice gets their professional profile.

Professionals became a core App for every account tier. Under an individual
tier (basic, medium, advanced) the account holder *is* the practice's
professional: patients, treatments and appointments are assigned to them, so
they need a directory profile, linked to their account — and their practice
has no directory screen to make one from.

New practices get it from ``HolderProfileService.ensure`` on
``clinic.created``; this gives it to the ones that already exist. The holder
is the practice's first admin membership. A practice whose holder already
has a linked profile is left alone, and so is any unlinked profile: telling
which one is the holder would be a guess (ADR 0032).

``license_number`` comes from ``users.professional_id``, the licence the
operator recorded when creating the account. Keys are ``gen_random_uuid()``,
as the module's earlier data migration made them.

Revision ID: pro_0004
Revises: pro_0003
Create Date: 2026-10-18

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "pro_0004"
down_revision: str | None = "pro_0003"
branch_labels: str | Sequence[str] | None = None
# Reads `clinics.account_tier`: on a fresh database `upgrade heads` must have
# built it first. Ordered without merging the branches (ADR 0002).
depends_on: str | Sequence[str] | None = ("0011",)


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO professionals (
                id, clinic_id, user_id, first_name, last_name, email,
                license_number, professional_type, is_active, created_at, updated_at
            )
            SELECT gen_random_uuid(), holder.clinic_id, holder.user_id,
                   COALESCE(u.first_name, ''), COALESCE(u.last_name, ''), u.email,
                   u.professional_id, 'dentist', true, now(), now()
            FROM (
                SELECT DISTINCT ON (m.clinic_id) m.clinic_id, m.user_id
                FROM clinic_memberships m
                JOIN clinics c ON c.id = m.clinic_id
                WHERE c.account_tier IN ('basic', 'medium', 'advanced')
                  AND m.role = 'admin'
                ORDER BY m.clinic_id, m.created_at, m.user_id
            ) AS holder
            JOIN users u ON u.id = holder.user_id
            WHERE NOT EXISTS (
                SELECT 1 FROM professionals p
                WHERE p.clinic_id = holder.clinic_id AND p.user_id = holder.user_id
            )
            """
        )
    )


def downgrade() -> None:
    # The profiles stay: by now appointments, plans and notes may name them,
    # and a profile this revision made cannot be told from one made since.
    pass
