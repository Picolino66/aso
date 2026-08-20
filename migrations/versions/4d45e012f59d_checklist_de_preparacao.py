"""Checklist de preparação para implementação (§10 do fluxo.md, wf §16) — ADR-0030.

Revision ID: 4d45e012f59d
Revises: ae6259d3dc8b
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "4d45e012f59d"
down_revision = "ae6259d3dc8b"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.add_column(
            sa.Column(
                "preparation_checklist", _JSONB, nullable=False, server_default=sa.text("'[]'")
            )
        )
        batch_op.add_column(sa.Column("dependency_task_id", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.drop_column("dependency_task_id")
        batch_op.drop_column("preparation_checklist")
