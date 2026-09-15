"""effort aplicado no registro de execucoes (ADR-0073, MEL-43)

Revision ID: 88bb8b412a7f
Revises: 84f292331b7a
Create Date: 2026-09-15 16:57:02.693589
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '88bb8b412a7f'
down_revision: str | None = '84f292331b7a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('agent_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('effort_aplicado', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('agent_runs', schema=None) as batch_op:
        batch_op.drop_column('effort_aplicado')
