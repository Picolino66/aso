"""jobs — fila persistida de execução (ADR-0067, MEL-31)

Sem FK para orchestrations: a fila fica fora da reescrita por nível do agregado.

Revision ID: ffabdb4f1996
Revises: accd40ad02c2
Create Date: 2026-09-15 12:13:05.823207
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = 'ffabdb4f1996'
down_revision: str | None = 'accd40ad02c2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('jobs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('orchestration_id', sa.String(), nullable=False),
    sa.Column('card_id', sa.String(), nullable=True),
    sa.Column('operacao', sa.String(), nullable=False),
    sa.Column('parametros', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('resultado', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=True),
    sa.Column('erro', sa.Text(), nullable=False),
    sa.Column('erro_status', sa.Integer(), nullable=True),
    sa.Column('ator', sa.String(), nullable=False),
    sa.Column('dono', sa.String(), nullable=False),
    sa.Column('criado_em', sa.String(), nullable=False),
    sa.Column('iniciado_em', sa.String(), nullable=True),
    sa.Column('fim', sa.String(), nullable=True),
    sa.Column('cancelamento_solicitado', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.create_index('ix_jobs_orch_criado', ['orchestration_id', 'criado_em'], unique=False)
        batch_op.create_index('ix_jobs_status_criado', ['status', 'criado_em'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_index('ix_jobs_status_criado')
        batch_op.drop_index('ix_jobs_orch_criado')

    op.drop_table('jobs')
