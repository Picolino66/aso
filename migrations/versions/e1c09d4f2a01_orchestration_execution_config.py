"""Configuração efetiva de execução por orquestração.

Revision ID: e1c09d4f2a01
Revises: b3d1f0a24c7e
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "e1c09d4f2a01"
down_revision = "b3d1f0a24c7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.add_column(sa.Column("selected_executor", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("selected_effort", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("validation_command", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("workspace_prepared", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.drop_column("workspace_prepared")
        batch_op.drop_column("validation_command")
        batch_op.drop_column("selected_effort")
        batch_op.drop_column("selected_executor")
