"""Incidente de primeira classe (§21 do fluxo.md, wf §27/§38) — ADR-0032.

Revision ID: 4ba98fa43986
Revises: 8decb7b48673
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "4ba98fa43986"
down_revision = "8decb7b48673"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("orchestration_id", sa.String(), nullable=False),
        sa.Column("card_id", sa.String(), nullable=True),
        sa.Column("titulo", sa.Text(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("gravidade", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("causa_raiz", sa.Text(), nullable=False),
        sa.Column("deploy_ambiente", sa.String(), nullable=False),
        sa.Column("deploy_estagio", sa.String(), nullable=False),
        sa.Column("deploy_versao", sa.Integer(), nullable=True),
        sa.Column("timeline", _JSONB, nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("resolved_at", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["orchestration_id"], ["orchestrations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.create_index(
            "ix_incidents_orch_status", ["orchestration_id", "status"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.drop_index("ix_incidents_orch_status")
    op.drop_table("incidents")
