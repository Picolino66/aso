"""Campo tipo em human_approvals (Dashboard §3.3, ADR-0037).

Revision ID: 8f4b6d1c9a2e
Revises: 7c1e9a5f2d4b
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op

revision = "8f4b6d1c9a2e"
down_revision = "7c1e9a5f2d4b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "human_approvals",
        sa.Column("tipo", sa.String(), nullable=False, server_default="manual"),
    )
    with op.batch_alter_table("human_approvals") as batch_op:
        batch_op.alter_column("tipo", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("human_approvals") as batch_op:
        batch_op.drop_column("tipo")
