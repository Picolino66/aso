"""agent_runs — registro persistido de execuções de agente (ADR-0065, MEL-30)

Sem FK para orchestrations: fica fora da reescrita por nível do agregado.

Revision ID: accd40ad02c2
Revises: e4b1c8382290
Create Date: 2026-09-15 09:31:30.817386
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = 'accd40ad02c2'
down_revision: str | None = 'e4b1c8382290'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('agent_runs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('orchestration_id', sa.String(), nullable=False),
    sa.Column('card_id', sa.String(), nullable=True),
    sa.Column('pr_id', sa.String(), nullable=True),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('task_type', sa.String(), nullable=False),
    sa.Column('papel', sa.String(), nullable=False),
    sa.Column('executor', sa.String(), nullable=False),
    sa.Column('modelo', sa.String(), nullable=False),
    sa.Column('effort', sa.String(), nullable=False),
    sa.Column('prompt_version', sa.String(), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('envelope', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('saida_resumo', sa.Text(), nullable=False),
    sa.Column('stdout_cauda', sa.Text(), nullable=False),
    sa.Column('exit_code', sa.Integer(), nullable=True),
    sa.Column('diff_lines', sa.Integer(), nullable=True),
    sa.Column('branch', sa.String(), nullable=True),
    sa.Column('inicio', sa.String(), nullable=False),
    sa.Column('fim', sa.String(), nullable=True),
    sa.Column('duracao_ms', sa.Float(), nullable=True),
    sa.Column('tokens_entrada', sa.Integer(), nullable=False),
    sa.Column('tokens_saida', sa.Integer(), nullable=False),
    sa.Column('tokens_cache', sa.Integer(), nullable=False),
    sa.Column('custo_usd', sa.Float(), nullable=False),
    sa.Column('uso_origem', sa.String(), nullable=False),
    sa.Column('erro', sa.Text(), nullable=False),
    sa.Column('decisao', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('request_id', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('agent_runs', schema=None) as batch_op:
        batch_op.create_index('ix_agent_runs_card', ['card_id'], unique=False)
        batch_op.create_index('ix_agent_runs_orch_inicio', ['orchestration_id', 'inicio'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('agent_runs', schema=None) as batch_op:
        batch_op.drop_index('ix_agent_runs_orch_inicio')
        batch_op.drop_index('ix_agent_runs_card')

    op.drop_table('agent_runs')
