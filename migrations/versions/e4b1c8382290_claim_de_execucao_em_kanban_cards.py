"""claim de execucao em kanban_cards (ADR-0058, MEL-13)

Colunas nulas: NULL = card livre. Cards existentes nascem livres (nenhuma execução
em voo sobrevive a uma migração com o runtime parado).

Revision ID: e4b1c8382290
Revises: 20755cca5b90
Create Date: 2026-09-15 01:51:44.135469
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'e4b1c8382290'
down_revision: str | None = '20755cca5b90'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('kanban_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('em_execucao_desde', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('execution_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('execucao_dono', sa.String(), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('kanban_cards', schema=None) as batch_op:
        batch_op.drop_column('execucao_dono')
        batch_op.drop_column('execution_id')
        batch_op.drop_column('em_execucao_desde')

