"""estrategias reduzidas e campos de plano removidos (ADR-0075, MEL-53)

Remove `planned_agents.parallel_group`/`allowed_tools` (nunca usados) e normaliza estratégias.

Revision ID: c3986f6a1a5d
Revises: 88bb8b412a7f
Create Date: 2026-09-15 17:39:41.124756
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'c3986f6a1a5d'
down_revision: str | None = '88bb8b412a7f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Estratégias que eram só rótulo viram a que descreve a execução real (ADR-0074/ADR-0075).
_MAPA = {
    "evaluator_optimizer": "sequential_agents",
    "supervisor_worker": "sequential_agents",
    "agents_as_tools": "sequential_agents",
    "handoff": "sequential_agents",
    "group_chat_controlled": "sequential_agents",
    "hybrid": "sequential_agents",
}


def upgrade() -> None:
    for antiga, nova in _MAPA.items():
        op.execute(
            sa.text("UPDATE execution_plans SET strategy = :nova WHERE strategy = :antiga").bindparams(
                nova=nova, antiga=antiga
            )
        )
    with op.batch_alter_table("planned_agents", schema=None) as batch_op:
        batch_op.drop_column("parallel_group")
        batch_op.drop_column("allowed_tools")


def downgrade() -> None:
    # A estratégia original não é recuperável (virou a de execução real); só as colunas voltam.
    with op.batch_alter_table("planned_agents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("allowed_tools", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("parallel_group", sa.String(), nullable=True))
