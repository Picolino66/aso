"""orchestration_target_path

Adiciona a coluna `target_path` em `orchestrations`: a pasta de trabalho
(workspace) por orquestração, que substitui o `ASO_TARGET_REPO` global só para
aquela orquestração. Nullable → orquestrações antigas continuam no comportamento
legado (repo/provider global).

Revision ID: b3d1f0a24c7e
Revises: 7a759f873114
Create Date: 2026-07-09 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'b3d1f0a24c7e'
down_revision: str | None = '7a759f873114'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('orchestrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('target_path', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('orchestrations', schema=None) as batch_op:
        batch_op.drop_column('target_path')
