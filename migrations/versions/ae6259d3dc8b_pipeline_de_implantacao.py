"""Pipeline de implantação multi-estágio (§19 do fluxo.md, wf §25) — ADR-0029.

Revision ID: ae6259d3dc8b
Revises: 1ce613a3ff28
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "ae6259d3dc8b"
down_revision = "1ce613a3ff28"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.add_column(
            sa.Column("deploy_pipeline", _JSONB, nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.drop_column("deploy_pipeline")
