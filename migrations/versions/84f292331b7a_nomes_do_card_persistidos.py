"""nomes do card persistidos (ADR-0071, MEL-35)

Revision ID: 84f292331b7a
Revises: 813ddb006951
Create Date: 2026-09-15 16:14:39.909007
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '84f292331b7a'
down_revision: str | None = '813ddb006951'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('kanban_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('branch_stem', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('commit_subject', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('kanban_cards', schema=None) as batch_op:
        batch_op.drop_column('commit_subject')
        batch_op.drop_column('branch_stem')
