"""Custo real e orçamento com freio (§1/§3.2 do plano7.md) — ADR-0026.

Revision ID: 1a9d4f0c7e5b
Revises: f65a28d4e213
Create Date: 2026-08-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "1a9d4f0c7e5b"
down_revision = "f65a28d4e213"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.add_column(
            sa.Column("uso", _JSONB, nullable=False, server_default=sa.text("'{}'"))
        )
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.add_column(sa.Column("orcamento_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.drop_column("orcamento_usd")
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.drop_column("uso")
