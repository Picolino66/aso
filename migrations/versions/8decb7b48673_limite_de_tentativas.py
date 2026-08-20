"""Limite de tentativas por card (§36.4 do wiframe) — ADR-0031.

Revision ID: 8decb7b48673
Revises: 4d45e012f59d
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "8decb7b48673"
down_revision = "4d45e012f59d"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.add_column(
            sa.Column("tentativa_atual", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("max_tentativas", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("tentativas", _JSONB, nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.drop_column("tentativas")
        batch_op.drop_column("max_tentativas")
        batch_op.drop_column("tentativa_atual")
