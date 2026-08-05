"""Documentos versionados + ficha de encerramento (§4.2/§4.5 do plano4.md) — ADR-0021.

Revision ID: c1a3e7f92b4d
Revises: 66b4f7a6563f
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "c1a3e7f92b4d"
down_revision = "66b4f7a6563f"
branch_labels = None
depends_on = None

# Mesmo tipo portável do ORM (src/aso/db/models.py): JSONB no Postgres, JSON no resto.
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.add_column(
            sa.Column("discovery_reports", _JSONB, nullable=False, server_default=sa.text("'[]'"))
        )
        batch_op.add_column(
            sa.Column("spec_documents", _JSONB, nullable=False, server_default=sa.text("'[]'"))
        )
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.add_column(
            sa.Column("closure", _JSONB, nullable=False, server_default=sa.text("'{}'"))
        )

    # Migra o `discovery_report` singular (ADR-0020) para o primeiro item do ring —
    # sem isto, orquestrações com discovery já rodado perderiam o relatório.
    orchestrations = sa.table(
        "orchestrations",
        sa.column("id", sa.String),
        sa.column("discovery_report", _JSONB),
        sa.column("discovery_reports", _JSONB),
    )
    rows = bind.execute(sa.select(orchestrations.c.id, orchestrations.c.discovery_report)).fetchall()
    for row in rows:
        relatorio = row.discovery_report or {}
        if not relatorio:
            continue
        relatorio = {**relatorio, "versao": relatorio.get("versao", 1)}
        bind.execute(
            orchestrations.update()
            .where(orchestrations.c.id == row.id)
            .values(discovery_reports=[relatorio])
        )

    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.drop_column("discovery_report")


def downgrade() -> None:
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.add_column(
            sa.Column("discovery_report", _JSONB, nullable=False, server_default=sa.text("'{}'"))
        )

    orchestrations = sa.table(
        "orchestrations",
        sa.column("id", sa.String),
        sa.column("discovery_report", _JSONB),
        sa.column("discovery_reports", _JSONB),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.select(orchestrations.c.id, orchestrations.c.discovery_reports)).fetchall()
    for row in rows:
        ring = row.discovery_reports or []
        bind.execute(
            orchestrations.update()
            .where(orchestrations.c.id == row.id)
            .values(discovery_report=ring[-1] if ring else {})
        )

    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.drop_column("discovery_reports")
        batch_op.drop_column("spec_documents")
    with op.batch_alter_table("kanban_cards") as batch_op:
        batch_op.drop_column("closure")
