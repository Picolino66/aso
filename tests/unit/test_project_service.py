"""Regras de domínio do catálogo multi-repo."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from aso.control.project_service import (
    ProjectConflictError,
    ProjectService,
    ProjectValidationError,
)
from aso.persistence.memory import InMemoryProjectRepository
from aso.shared.types import ProjectStatus


def test_criacao_exige_nome_e_pasta_existente(tmp_path: Path) -> None:
    service = ProjectService(InMemoryProjectRepository())

    with pytest.raises(ProjectValidationError, match="Nome"):
        service.create(name="  ", description="", target_path=str(tmp_path), actor="op")
    with pytest.raises(ProjectValidationError, match="não existe"):
        service.create(
            name="Projeto",
            description="",
            target_path=str(tmp_path / "ausente"),
            actor="op",
        )


def test_path_e_canonico_e_unico_inclusive_quando_arquivado(tmp_path: Path) -> None:
    repository = InMemoryProjectRepository()
    service = ProjectService(repository)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)

    project = service.create(
        name=" Catálogo ", description=" teste ", target_path=str(alias), actor="op"
    )
    service.archive(project.id, actor="adm")

    assert project.target_path == str(tmp_path.resolve())
    assert project.name == "Catálogo"
    assert service.list_projects() == []
    assert service.list_projects(include_archived=True)[0].status == ProjectStatus.ARCHIVED
    with pytest.raises(ProjectConflictError, match="restaure-o"):
        service.create(name="Duplicado", description="", target_path=str(tmp_path), actor="op")


def test_atualizacao_arquivo_restauracao_e_eventos(tmp_path: Path) -> None:
    first = tmp_path / "primeiro"
    second = tmp_path / "segundo"
    first.mkdir()
    second.mkdir()
    service = ProjectService(InMemoryProjectRepository())
    project = service.create(
        name="Projeto", description="inicial", target_path=str(first), actor="criador"
    )

    updated = service.update(
        project.id,
        name="Projeto novo",
        description="alterado",
        target_path=str(second),
        actor="editor",
    )
    archived = service.archive(project.id, actor="admin")
    restored = service.restore(project.id, actor="admin", target_path=str(first))

    assert updated.target_path == str(second.resolve())
    assert archived.archived_at is not None
    assert restored.status == ProjectStatus.ACTIVE
    assert restored.archived_at is None
    assert restored.target_path == str(first.resolve())
    events = service.events(project.id)
    assert [event.type for event in events] == [
        "ProjectCreated",
        "ProjectUpdated",
        "ProjectArchived",
        "ProjectRestored",
    ]
    assert [event.actor for event in events] == ["criador", "editor", "admin", "admin"]
    assert events[1].before["description"] == "inicial"
    assert events[1].after["description"] == "alterado"


def test_edicao_de_arquivado_exige_restauracao(tmp_path: Path) -> None:
    service = ProjectService(InMemoryProjectRepository())
    project = service.create(name="Projeto", description="", target_path=str(tmp_path), actor="op")
    service.archive(project.id, actor="adm")

    with pytest.raises(ProjectConflictError, match="Restaure"):
        service.update(
            project.id,
            name="Outro",
            description=None,
            target_path=None,
            actor="op",
        )


def test_concorrencia_nao_cria_dois_projetos_para_o_mesmo_path(tmp_path: Path) -> None:
    repository = InMemoryProjectRepository()
    barrier = Barrier(2)

    def create(name: str) -> str:
        service = ProjectService(repository)
        barrier.wait()
        try:
            return service.create(
                name=name, description="", target_path=str(tmp_path), actor=name
            ).id
        except ProjectConflictError:
            return "conflito"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ["A", "B"]))

    assert results.count("conflito") == 1
    assert len(repository.list_projects()) == 1
