"""Executor por etapa da esteira (F1..F7 + naming) — ADR-0014.

Revision ID: a7f5c2b91d40
Revises: f84c2a1d9e30
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "a7f5c2b91d40"
down_revision = "f84c2a1d9e30"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "agent_assignments",
                _JSONB,
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.drop_column("agent_assignments")
