"""Ficha estruturada da demanda (§1/§2 do fluxo.md) — ADR-0016.

Revision ID: 40812903e932
Revises: a7f5c2b91d40
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "40812903e932"
down_revision = "a7f5c2b91d40"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "demand_brief",
                _JSONB,
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.drop_column("demand_brief")
