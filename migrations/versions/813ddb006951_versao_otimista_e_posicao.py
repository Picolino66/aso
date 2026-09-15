"""versao otimista e posicao das colecoes (ADR-0068, MEL-33)

Orquestrações já gravadas começam na versão 1 (a versão 0 significa "ainda não gravada").

Revision ID: 813ddb006951
Revises: ffabdb4f1996
Create Date: 2026-09-15 14:57:26.835816
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '813ddb006951'
down_revision: str | None = 'ffabdb4f1996'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('bug_reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('candidate_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('card_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('conflicts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('context_patches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('human_approvals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('incidents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('kanban_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('orchestrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('versao', sa.Integer(), server_default='0', nullable=False))
    op.execute("UPDATE orchestrations SET versao = 1")

    with op.batch_alter_table('pull_requests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('quality_gate_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('review_comments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('slo_evaluations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('snapshots', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posicao', sa.Integer(), server_default='0', nullable=False))



def downgrade() -> None:
    with op.batch_alter_table('snapshots', schema=None) as batch_op:
        batch_op.drop_column('posicao')

    with op.batch_alter_table('slo_evaluations', schema=None) as batch_op:
        batch_op.drop_column('posicao')

    with op.batch_alter_table('review_comments', schema=None) as batch_op:
        batch_op.drop_column('posicao')

    with op.batch_alter_table('quality_gate_results', schema=None) as batch_op:
        batch_op.drop_column('posicao')

    with op.batch_alter_table('pull_requests', schema=None) as batch_op:
        batch_op.drop_column('posicao')

    with op.batch_alter_table('orchestrations', schema=None) as batch_op:
        batch_op.drop_column('versao')

    with op.batch_alter_table('kanban_cards', schema=None) as batch_op:
        batch_op.drop_column('posicao')

    with op.batch_alter_table('incidents', schema=None) as batch_op:
        batch_op.drop_column('posicao')

    with op.batch_alter_table('human_approvals', schema=None) as batch_op:
        batch_op.drop_column('posicao')

    with op.batch_alter_table('context_patches', schema=None) as batch_op:
        batch_op.drop_column('posicao')

    with op.batch_alter_table('conflicts', schema=None) as batch_op:
        batch_op.drop_column('posicao')

    with op.batch_alter_table('card_events', schema=None) as batch_op:
        batch_op.drop_column('posicao')

    with op.batch_alter_table('candidate_runs', schema=None) as batch_op:
        batch_op.drop_column('posicao')

    with op.batch_alter_table('bug_reports', schema=None) as batch_op:
        batch_op.drop_column('posicao')

