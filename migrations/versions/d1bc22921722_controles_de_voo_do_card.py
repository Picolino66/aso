"""Controles em voo do card (Tela 15, wf §17.2, ADR-0048).

Revision ID: d1bc22921722
Revises: 9c89dc38ffcc
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d1bc22921722"
down_revision = "9c89dc38ffcc"
branch_labels = None
depends_on = None

_JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("kanban_cards", schema=None) as batch_op:
        batch_op.add_column(sa.Column("effort_override", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("executor_override", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "pausado", sa.Boolean(), nullable=False, server_default=sa.text("false")
            )
        )
        batch_op.add_column(
            sa.Column(
                "contexto_adicional", _JSONB, nullable=False, server_default=sa.text("'[]'")
            )
        )
    with op.batch_alter_table("kanban_cards", schema=None) as batch_op:
        batch_op.alter_column("pausado", server_default=None)
        batch_op.alter_column("contexto_adicional", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("kanban_cards", schema=None) as batch_op:
        batch_op.drop_column("contexto_adicional")
        batch_op.drop_column("pausado")
        batch_op.drop_column("executor_override")
        batch_op.drop_column("effort_override")
