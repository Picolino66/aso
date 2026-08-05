"""Hierarquia de cards e QA manual (§7/§16/§17 do fluxo.md) — ADR-0025.

Revision ID: f65a28d4e213
Revises: e2c481f6b3a7
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "f65a28d4e213"
down_revision = "e2c481f6b3a7"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.add_column(
            sa.Column("qa_checks", _JSONB, nullable=False, server_default=sa.text("'[]'"))
        )
        batch_op.add_column(sa.Column("parent_id", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.drop_column("qa_checks")
        batch_op.drop_column("parent_id")
