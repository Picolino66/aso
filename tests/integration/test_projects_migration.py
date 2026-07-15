"""Backfill de IDs legados na migração do catálogo multi-repo."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from pytest import MonkeyPatch
from sqlalchemy import create_engine, text


def test_migracao_cria_projetos_arquivados_e_neutraliza_paths_conflitantes(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = Path(__file__).parents[2]
    database = tmp_path / "legacy.db"
    url = f"sqlite:///{database}"
    monkeypatch.setenv("ASO_DATABASE_URL", url)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "e1c09d4f2a01")
    engine = create_engine(url)
    values = {
        "execution_mode": "full-pipeline",
        "current_phase": "F1",
        "snapshot_version": "O0",
        "status": "created",
        "user_request": "legado",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "workspace_prepared": False,
    }
    with engine.begin() as connection:
        for orchestration_id, project_id, target_path in (
            ("orch-a", "proj-a", "/repo/compartilhado"),
            ("orch-b", "proj-b", "/repo/compartilhado"),
            ("orch-c", "proj-c", "/repo/unico"),
        ):
            connection.execute(
                text(
                    "INSERT INTO orchestrations "
                    "(id, project_id, target_path, execution_mode, current_phase, "
                    "snapshot_version, status, user_request, created_at, updated_at, "
                    "workspace_prepared) VALUES "
                    "(:id, :project_id, :target_path, :execution_mode, :current_phase, "
                    ":snapshot_version, :status, :user_request, :created_at, :updated_at, "
                    ":workspace_prepared)"
                ),
                {
                    **values,
                    "id": orchestration_id,
                    "project_id": project_id,
                    "target_path": target_path,
                },
            )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        projects = {
            row.id: (row.target_path, row.status)
            for row in connection.execute(
                text("SELECT id, target_path, status FROM projects ORDER BY id")
            )
        }
        events = list(
            connection.execute(
                text("SELECT project_id, type, actor FROM project_events ORDER BY project_id")
            )
        )
    assert projects == {
        "proj-a": (None, "archived"),
        "proj-b": (None, "archived"),
        "proj-c": ("/repo/unico", "archived"),
    }
    assert [(row.type, row.actor) for row in events] == [
        ("LegacyProjectBackfilled", "migration"),
        ("LegacyProjectBackfilled", "migration"),
        ("LegacyProjectBackfilled", "migration"),
    ]
