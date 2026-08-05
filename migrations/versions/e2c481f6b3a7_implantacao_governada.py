"""Implantação governada (§18-22 do fluxo.md) — ADR-0023.

Revision ID: e2c481f6b3a7
Revises: a7f13c6e9d02
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "e2c481f6b3a7"
down_revision = "a7f13c6e9d02"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.add_column(sa.Column("deploy_command", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "deploy_environment",
                sa.String(),
                nullable=False,
                server_default="producao",
            )
        )
        batch_op.add_column(
            sa.Column("deploy_health_checks", _JSONB, nullable=False, server_default=sa.text("'[]'"))
        )
        batch_op.add_column(sa.Column("deploy_rollback_command", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("deploy_runs", _JSONB, nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.drop_column("deploy_command")
        batch_op.drop_column("deploy_environment")
        batch_op.drop_column("deploy_health_checks")
        batch_op.drop_column("deploy_rollback_command")
        batch_op.drop_column("deploy_runs")
