"""Catálogo multi-repo persistente e governado.

Revision ID: f84c2a1d9e30
Revises: e1c09d4f2a01
Create Date: 2026-07-14
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = "f84c2a1d9e30"
down_revision: str | None = "e1c09d4f2a01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _backfill_legacy_projects() -> None:
    """Preserva project_ids antigos antes de ativar as novas FKs restritivas."""
    bind = op.get_bind()
    orchestration_rows = bind.execute(
        sa.text(
            "SELECT project_id, target_path, created_at FROM orchestrations "
            "WHERE project_id IS NOT NULL"
        )
    ).mappings()
    board_ids = {
        str(row[0])
        for row in bind.execute(
            sa.text("SELECT DISTINCT project_id FROM boards WHERE project_id IS NOT NULL")
        )
    }

    paths: dict[str, set[str]] = defaultdict(set)
    created: dict[str, str] = {}
    project_ids = set(board_ids)
    for row in orchestration_rows:
        project_id = str(row["project_id"])
        project_ids.add(project_id)
        if row["target_path"]:
            paths[project_id].add(str(row["target_path"]))
        timestamp = str(row["created_at"])
        created[project_id] = min(created.get(project_id, timestamp), timestamp)

    candidates = {
        project_id: next(iter(values))
        for project_id, values in paths.items()
        if len(values) == 1
    }
    duplicated_paths = {
        path for path, count in Counter(candidates.values()).items() if count > 1
    }
    timestamp = _now()
    projects = sa.table(
        "projects",
        sa.column("id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("target_path", sa.String()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.String()),
        sa.column("updated_at", sa.String()),
        sa.column("archived_at", sa.String()),
    )
    events = sa.table(
        "project_events",
        sa.column("id", sa.String()),
        sa.column("project_id", sa.String()),
        sa.column("type", sa.String()),
        sa.column("actor", sa.String()),
        sa.column("before", _JSON),
        sa.column("after", _JSON),
        sa.column("created_at", sa.String()),
    )
    for project_id in sorted(project_ids):
        path = candidates.get(project_id)
        if path in duplicated_paths:
            path = None
        payload: dict[str, Any] = {
            "id": project_id,
            "name": f"Projeto legado {project_id}",
            "description": "Criado pela migração do catálogo multi-repo.",
            "target_path": path,
            "status": "archived",
            "created_at": created.get(project_id, timestamp),
            "updated_at": timestamp,
            "archived_at": timestamp,
        }
        bind.execute(projects.insert().values(**payload))
        bind.execute(
            events.insert().values(
                id=f"projevt_{uuid.uuid4().hex}",
                project_id=project_id,
                type="LegacyProjectBackfilled",
                actor="migration",
                before={},
                after=payload,
                created_at=timestamp,
            )
        )


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("target_path", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("archived_at", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_path", name="uq_projects_target_path"),
    )
    with op.batch_alter_table("projects") as batch_op:
        batch_op.create_index("ix_projects_status", ["status"], unique=False)
        batch_op.create_index("ix_projects_created_at", ["created_at"], unique=False)

    op.create_table(
        "project_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("before", _JSON, nullable=False),
        sa.Column("after", _JSON, nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("project_events") as batch_op:
        batch_op.create_index("ix_project_events_project_id", ["project_id"], unique=False)
        batch_op.create_index("ix_project_events_type", ["type"], unique=False)
        batch_op.create_index("ix_project_events_created_at", ["created_at"], unique=False)

    _backfill_legacy_projects()

    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.create_foreign_key(
            "fk_orchestrations_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("boards") as batch_op:
        batch_op.create_foreign_key(
            "fk_boards_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("boards") as batch_op:
        batch_op.drop_constraint("fk_boards_project_id_projects", type_="foreignkey")
    with op.batch_alter_table("orchestrations") as batch_op:
        batch_op.drop_constraint("fk_orchestrations_project_id_projects", type_="foreignkey")
    op.drop_table("project_events")
    op.drop_table("projects")
