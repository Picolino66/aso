"""Duração real por critério de quality gate (Tela 16, wf §18.2, ADR-0048).

Revision ID: d07dfbac77c5
Revises: d1bc22921722
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d07dfbac77c5"
down_revision = "d1bc22921722"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("gate_criteria", schema=None) as batch_op:
        batch_op.add_column(sa.Column("duration_ms", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("gate_criteria", schema=None) as batch_op:
        batch_op.drop_column("duration_ms")
