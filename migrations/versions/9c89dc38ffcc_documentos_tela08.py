"""Documentos da Tela 08 (wf §10, ADR-0046).

Revision ID: 9c89dc38ffcc
Revises: 8f4b6d1c9a2e
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "9c89dc38ffcc"
down_revision = "8f4b6d1c9a2e"
branch_labels = None
depends_on = None

_JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("orchestrations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("documentos", _JSONB, nullable=False, server_default=sa.text("'{}'"))
        )
        batch_op.add_column(
            sa.Column(
                "documento_comentarios", _JSONB, nullable=False, server_default=sa.text("'[]'")
            )
        )
    with op.batch_alter_table("orchestrations", schema=None) as batch_op:
        batch_op.alter_column("documentos", server_default=None)
        batch_op.alter_column("documento_comentarios", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("orchestrations", schema=None) as batch_op:
        batch_op.drop_column("documento_comentarios")
        batch_op.drop_column("documentos")
