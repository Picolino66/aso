"""Regras de roteamento SE/ENTÃO (§33 do wireframe, §9 do fluxo.md) — ADR-0028.

Revision ID: 1ce613a3ff28
Revises: 1a9d4f0c7e5b
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "1ce613a3ff28"
down_revision = "1a9d4f0c7e5b"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "routing_rules",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("nome", sa.String(), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("ativa", sa.Boolean(), nullable=False),
        sa.Column("precedencia", sa.Integer(), nullable=False),
        sa.Column("condicoes", _JSONB, nullable=False),
        sa.Column("acao", _JSONB, nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("routing_rules") as batch_op:
        batch_op.create_index("ix_routing_rules_ativa", ["ativa"], unique=False)
        batch_op.create_index("ix_routing_rules_created_at", ["created_at"], unique=False)

    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.add_column(sa.Column("routing_rule_applied", _JSONB, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.drop_column("routing_rule_applied")
    op.drop_table("routing_rules")
