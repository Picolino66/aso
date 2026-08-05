"""Bateria de validações nomeada (§12 do fluxo.md) — ADR-0022.

Revision ID: a7f13c6e9d02
Revises: c1a3e7f92b4d
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "a7f13c6e9d02"
down_revision = "c1a3e7f92b4d"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.add_column(
            sa.Column("validation_checks", _JSONB, nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.drop_column("validation_checks")
