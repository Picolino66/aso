"""Discovery e aprovação (§3/§4) — ADR-0020.

Revision ID: 66b4f7a6563f
Revises: 774265ae4b87
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "66b4f7a6563f"
down_revision = "774265ae4b87"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.add_column(
            sa.Column("discovery_report", _JSONB, nullable=False, server_default=sa.text("'{}'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.drop_column("discovery_report")
