"""Roteamento de falha (§13/§8 do fluxo.md) — ADR-0019.

Revision ID: 774265ae4b87
Revises: b6e2f4a91c53
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "774265ae4b87"
down_revision = "b6e2f4a91c53"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.add_column(
            sa.Column("failures", _JSONB, nullable=False, server_default=sa.text("'[]'"))
        )
    with op.batch_alter_table("card_events") as batch_op:
        batch_op.add_column(
            sa.Column("reason", sa.Text(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("result", sa.Text(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
        batch_op.add_column(
            sa.Column("next_action", sa.Text(), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("card_events") as batch_op:
        batch_op.drop_column("next_action")
        batch_op.drop_column("evidence")
        batch_op.drop_column("result")
        batch_op.drop_column("reason")
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.drop_column("failures")
