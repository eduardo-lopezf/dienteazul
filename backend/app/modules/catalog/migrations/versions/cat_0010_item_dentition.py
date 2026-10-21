"""Which teeth a treatment can be done on.

`dentition` is `both` (any tooth), `deciduous` (primary teeth only) or
`permanent`. The odontogram offers a treatment only on the dentition it fits
and refuses it on a tooth of the other one.

Every existing row starts as `both`. The reference's own copies — rows the
seed wrote (`is_system`) — then take the value the reference gives them; the
codes are frozen here as they stood when the field was introduced, so a later
change to the reference files does not rewrite history. A clinic's own
treatments stay `both` until an administrator says otherwise.

Revision ID: cat_0010
Revises: cat_0009
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cat_0010"
down_revision: str | None = "cat_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DECIDUOUS = (
    "ENDO-PED",
    "PED-ART",
    "PED-CROWN-STRIP",
    "PED-CROWN-ZIR",
    "PED-EXT-ANKYL",
    "PED-EXT-TEMP",
    "PED-FILL-GIC",
    "PED-FILL-TEMP",
    "PED-HALL",
    "PED-IPC",
    "PED-NATAL",
    "PED-PULPECTOMY",
    "PED-PULPOTOMY",
    "PED-PULPOTOMY-MTA",
    "PED-SDF",
)

PERMANENT = (
    "ENDO-4CANAL",
    "ENDO-APEX-MTA",
    "ENDO-APICOFORM",
    "ENDO-BI",
    "ENDO-BLEACH-INT",
    "ENDO-CALCIF",
    "ENDO-HEMISECT",
    "ENDO-INTENT-REPL",
    "ENDO-MICROSURG",
    "ENDO-MULTI",
    "ENDO-POST-FIBER",
    "ENDO-POST-METAL",
    "ENDO-POST-REMOVE",
    "ENDO-PULPOTOMY-PART",
    "ENDO-RETREAT",
    "ENDO-RETREAT-MULTI",
    "ENDO-RETREAT-UNI",
    "ENDO-REVASC",
    "ENDO-ROOT-AMP",
    "ENDO-UNI",
    "EST-VEN-DISI",
    "EST-VEN-INJECT",
    "EST-VEN-PREPLESS",
    "EST-VEN-PROV",
    "EST-VEN-RECEMENT",
    "EST-VEN-REPAIR",
    "GER-ROOT-KEEP",
    "IMP-2ND-STAGE",
    "IMP-ABUT-CUSTOM",
    "IMP-BLOCK",
    "IMP-BRIDGE",
    "IMP-IMMEDIATE",
    "IMP-IMMEDIATE-LOAD",
    "IMP-LOCATOR",
    "IMP-MINI",
    "IMP-NARROW",
    "IMP-PTERYG",
    "IMP-REMOVE",
    "IMP-RIDGE-SPLIT",
    "IMP-SCREW",
    "IMP-SHORT",
    "IMP-TI-MESH",
    "IMP-ZYGO",
    "LAB-BRIDGE-UNIT",
    "LAB-CROWN-DISI",
    "LAB-CROWN-MC",
    "LAB-CROWN-ZIR",
    "LAB-IMPL-ABUT",
    "LAB-IMPL-CROWN",
    "LAB-INLAY",
    "LAB-POST-CORE",
    "LAB-VENEER",
    "PED-APEXOG",
    "PED-FILL-PERM",
    "PED-MIH",
    "PERIO-IMPL-STM",
    "PERIO-MUCOSITIS",
    "REST-BRIDGE-DISI",
    "REST-BRIDGE-FIBER",
    "REST-BRIDGE-MARY",
    "REST-BRIDGE-MC",
    "REST-BRIDGE-PROV",
    "REST-BRIDGE-RECEMENT",
    "REST-BRIDGE-ZIR",
    "REST-CORE",
    "REST-CROWN-CADCAM",
    "REST-CROWN-DISI",
    "REST-CROWN-GOLD",
    "REST-CROWN-IMPL-MC",
    "REST-CROWN-IMPL-PROV",
    "REST-CROWN-IMPL-ZIR",
    "REST-CROWN-MC",
    "REST-CROWN-METAL",
    "REST-CROWN-PFZ",
    "REST-CROWN-POST-ENDO",
    "REST-CROWN-PROV",
    "REST-CROWN-PROV-LONG",
    "REST-CROWN-RECEMENT",
    "REST-CROWN-ZIR",
    "REST-DEF-ABUT",
    "REST-ENDOCROWN",
    "REST-HEAL-ABUT",
    "REST-INLAY-CER",
    "REST-INLAY-COMP",
    "REST-INLAY-GOLD",
    "REST-INLAY-PROV",
    "REST-OVER-CER",
    "REST-OVER-COMP",
    "REST-PIN",
    "REST-TABLETOP",
    "REST-VEN-COMP",
    "REST-VEN-PORC",
    "REST-VEN-ZIR",
    "SURG-APEC",
    "SURG-BONE-HORIZ",
    "SURG-BONE-VERT",
    "SURG-EXT-3M-IMPACT",
    "SURG-EXT-3MOLAR",
    "SURG-GERMECT",
    "SURG-IMP-TI",
    "SURG-IMP-ZIR",
    "SURG-PERIIMP",
    "SURG-SINUS",
    "SURG-SINUS-CLOSED",
)


def upgrade() -> None:
    op.add_column(
        "treatment_catalog_items",
        sa.Column("dentition", sa.String(20), server_default="both", nullable=False),
    )
    op.create_check_constraint(
        "ck_catalog_items_dentition",
        "treatment_catalog_items",
        "dentition IN ('both', 'deciduous', 'permanent')",
    )
    items = sa.table(
        "treatment_catalog_items",
        sa.column("internal_code", sa.String),
        sa.column("is_system", sa.Boolean),
        sa.column("dentition", sa.String),
    )
    for dentition, codes in (("deciduous", DECIDUOUS), ("permanent", PERMANENT)):
        op.execute(
            items.update()
            .where(items.c.is_system.is_(True), items.c.internal_code.in_(codes))
            .values(dentition=dentition)
        )


def downgrade() -> None:
    op.drop_constraint("ck_catalog_items_dentition", "treatment_catalog_items", type_="check")
    op.drop_column("treatment_catalog_items", "dentition")
