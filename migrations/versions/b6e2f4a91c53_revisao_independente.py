"""Revisão independente de código (§14/§15) — ADR-0017.

Revision ID: b6e2f4a91c53
Revises: 40812903e932
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b6e2f4a91c53"
down_revision = "40812903e932"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.add_column(sa.Column("executor", sa.String(), nullable=True))
    with op.batch_alter_table("pull_requests") as batch_op:
        batch_op.add_column(
            sa.Column("review_verdict", _JSONB, nullable=False, server_default=sa.text("'{}'"))
        )
        batch_op.add_column(
            sa.Column("reviewed_by", sa.String(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("review_rounds", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("pull_requests") as batch_op:
        batch_op.drop_column("review_rounds")
        batch_op.drop_column("reviewed_by")
        batch_op.drop_column("review_verdict")
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.drop_column("executor")
