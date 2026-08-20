"""Comentário de revisão ancorado em arquivo/linha (wf §20.3) — ADR-0033.

Revision ID: 7c1e9a5f2d4b
Revises: 4ba98fa43986
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op

revision = "7c1e9a5f2d4b"
down_revision = "4ba98fa43986"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_comments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("orchestration_id", sa.String(), nullable=False),
        sa.Column("pr_id", sa.String(), nullable=False),
        sa.Column("card_id", sa.String(), nullable=True),
        sa.Column("arquivo", sa.String(), nullable=False),
        sa.Column("linha", sa.Integer(), nullable=False),
        sa.Column("categoria", sa.String(), nullable=False),
        sa.Column("severidade", sa.String(), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("sugestao", sa.Text(), nullable=False),
        sa.Column("obrigatorio", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("resolved_by", sa.String(), nullable=False),
        sa.Column("resolved_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["orchestration_id"], ["orchestrations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("review_comments") as batch_op:
        batch_op.create_index(
            "ix_review_comments_orch_pr", ["orchestration_id", "pr_id", "status"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("review_comments") as batch_op:
        batch_op.drop_index("ix_review_comments_orch_pr")
    op.drop_table("review_comments")
