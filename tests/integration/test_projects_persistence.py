"""Persistência relacional e isolamento de workspaces por projeto."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aso.control.models import ProjectEvent
from aso.control.orchestration_service import OrchestrationService
from aso.db.models import ProjectEventRow, ProjectRow
from aso.db.repository import SqlAlchemyOrchestrationRepository, SqlAlchemyProjectRepository


def service(url: str) -> OrchestrationService:
    return OrchestrationService(
        repository=SqlAlchemyOrchestrationRepository(url),
        project_repository=SqlAlchemyProjectRepository(url),
    )


def test_catalogo_e_vinculos_sobrevivem_ao_reinicio(tmp_path: Path) -> None:
    first = tmp_path / "primeiro"
    second = tmp_path / "segundo"
    first.mkdir()
    second.mkdir()
    url = f"sqlite:///{tmp_path / 'projects.db'}"
    initial = service(url)
    project = initial.create_project(
        name="Runtime", description="catálogo", target_path=str(first), actor="op"
    )
    old_orchestration = initial.create_orchestration("primeira", project_id=project.id)
    initial.update_project(
        project.id,
        name=None,
        description=None,
        target_path=str(second),
        actor="op",
    )
    new_orchestration = initial.create_orchestration("segunda", project_id=project.id)

    restarted = service(url)

    assert restarted.get_project(project.id).name == "Runtime"
    assert restarted.get(old_orchestration.id).target_path == str(first.resolve())
    assert restarted.get(new_orchestration.id).target_path == str(second.resolve())
    assert {item.id for item in restarted.list_all(project_id=project.id)} == {
        old_orchestration.id,
        new_orchestration.id,
    }
    assert [event.type for event in restarted.project_events(project.id)] == [
        "ProjectCreated",
        "ProjectUpdated",
    ]


def test_fks_restritivas_impedem_apagar_projeto_referenciado(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    url = f"sqlite:///{tmp_path / 'foreign-keys.db'}"
    runtime = service(url)
    project = runtime.create_project(
        name="Protegido", description="", target_path=str(workspace), actor="op"
    )
    runtime.create_orchestration("preservar", project_id=project.id)
    repository = SqlAlchemyProjectRepository(url)

    orchestration_fks = inspect(repository.engine).get_foreign_keys("orchestrations")
    board_fks = inspect(repository.engine).get_foreign_keys("boards")
    assert any(fk["referred_table"] == "projects" for fk in orchestration_fks)
    assert any(fk["referred_table"] == "projects" for fk in board_fks)

    with pytest.raises(IntegrityError), Session(repository.engine) as session:
        session.execute(delete(ProjectEventRow).where(ProjectEventRow.project_id == project.id))
        session.execute(delete(ProjectRow).where(ProjectRow.id == project.id))
        session.commit()


def test_escrita_otimista_rejeita_update_obsoleto(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    url = f"sqlite:///{tmp_path / 'optimistic.db'}"
    runtime = service(url)
    project = runtime.create_project(
        name="Concorrente", description="", target_path=str(workspace), actor="op"
    )
    repository = SqlAlchemyProjectRepository(url)
    first = repository.get_project(project.id)
    stale = repository.get_project(project.id)
    assert first is not None and stale is not None
    first_before = first.model_dump(mode="json")
    first.description = "primeiro escritor"
    first.updated_at = "2030-01-01T00:00:00+00:00"
    repository.save_project(
        first,
        ProjectEvent(
            project_id=first.id,
            type="ProjectUpdated",
            actor="primeiro",
            before=first_before,
            after=first.model_dump(mode="json"),
        ),
    )
    stale_before = stale.model_dump(mode="json")
    stale.description = "escrita obsoleta"
    stale.updated_at = "2030-01-02T00:00:00+00:00"

    with pytest.raises(ValueError, match="outra operação"):
        repository.save_project(
            stale,
            ProjectEvent(
                project_id=stale.id,
                type="ProjectUpdated",
                actor="atrasado",
                before=stale_before,
                after=stale.model_dump(mode="json"),
            ),
        )

    assert repository.get_project(project.id).description == "primeiro escritor"  # type: ignore[union-attr]
    assert [event.actor for event in repository.list_project_events(project.id)] == [
        "op",
        "primeiro",
    ]
