"""Casos de uso do catálogo multi-repo.

Projetos são metadados de controle e não fazem parte do contexto canônico de uma
orquestração. Por isso, seu ciclo de vida é persistido por porta própria, com
eventos append-only, sem contornar o ContextBus.
"""

from __future__ import annotations

import threading

from aso.control.models import Project, ProjectEvent
from aso.execution.workspace import WorkspaceService
from aso.persistence.ports import ProjectRepository
from aso.shared.ids import now_iso
from aso.shared.types import ProjectStatus


class ProjectNotFoundError(LookupError):
    """Projeto solicitado não existe."""


class ProjectValidationError(ValueError):
    """Entrada de projeto é inválida."""


class ProjectConflictError(ValueError):
    """Operação conflita com o estado atual do catálogo."""


class ProjectService:
    """Coordena validação, persistência e auditoria de projetos."""

    def __init__(
        self,
        repository: ProjectRepository,
        workspace: WorkspaceService | None = None,
    ) -> None:
        self._repo = repository
        self._workspace = workspace or WorkspaceService()
        self._lock = threading.RLock()

    def _path(self, value: str | None) -> str:
        if value is None or not value.strip():
            raise ProjectValidationError("Informe a pasta do projeto.")
        try:
            return str(self._workspace.validate(value).resolve())
        except ValueError as exc:
            raise ProjectValidationError(str(exc)) from exc

    @staticmethod
    def _name(value: str) -> str:
        name = value.strip()
        if not name:
            raise ProjectValidationError("Nome do projeto é obrigatório.")
        return name

    def _get(self, project_id: str) -> Project:
        project = self._repo.get_project(project_id)
        if project is None:
            raise ProjectNotFoundError("Projeto inexistente.")
        return project

    def _ensure_unique_path(self, target_path: str, *, except_id: str | None = None) -> None:
        found = self._repo.get_project_by_path(target_path)
        if found is not None and found.id != except_id:
            action = "restaure-o" if found.status == ProjectStatus.ARCHIVED else "use-o"
            raise ProjectConflictError(
                f"A pasta já pertence ao projeto '{found.name}'; {action} em vez de duplicar."
            )

    def _save(self, project: Project, event: ProjectEvent) -> None:
        try:
            self._repo.save_project(project, event)
        except ValueError as exc:
            raise ProjectConflictError(str(exc)) from exc

    def create(
        self,
        *,
        name: str,
        description: str,
        target_path: str,
        actor: str,
    ) -> Project:
        with self._lock:
            canonical = self._path(target_path)
            self._ensure_unique_path(canonical)
            project = Project(
                name=self._name(name),
                description=description.strip(),
                target_path=canonical,
            )
            event = ProjectEvent(
                project_id=project.id,
                type="ProjectCreated",
                actor=actor,
                after=project.model_dump(mode="json"),
            )
            self._save(project, event)
            return project

    def list_projects(self, *, include_archived: bool = False) -> list[Project]:
        return self._repo.list_projects(include_archived=include_archived)

    def get(self, project_id: str) -> Project:
        return self._get(project_id)

    def update(
        self,
        project_id: str,
        *,
        name: str | None,
        description: str | None,
        target_path: str | None,
        actor: str,
    ) -> Project:
        with self._lock:
            project = self._get(project_id)
            if project.status == ProjectStatus.ARCHIVED:
                raise ProjectConflictError("Restaure o projeto antes de editá-lo.")
            before = project.model_dump(mode="json")
            if name is not None:
                project.name = self._name(name)
            if description is not None:
                project.description = description.strip()
            if target_path is not None:
                canonical = self._path(target_path)
                self._ensure_unique_path(canonical, except_id=project.id)
                project.target_path = canonical
            project.updated_at = now_iso()
            event = ProjectEvent(
                project_id=project.id,
                type="ProjectUpdated",
                actor=actor,
                before=before,
                after=project.model_dump(mode="json"),
            )
            self._save(project, event)
            return project

    def archive(self, project_id: str, *, actor: str) -> Project:
        with self._lock:
            project = self._get(project_id)
            if project.status == ProjectStatus.ARCHIVED:
                return project
            before = project.model_dump(mode="json")
            timestamp = now_iso()
            project.status = ProjectStatus.ARCHIVED
            project.archived_at = timestamp
            project.updated_at = timestamp
            self._save(
                project,
                ProjectEvent(
                    project_id=project.id,
                    type="ProjectArchived",
                    actor=actor,
                    before=before,
                    after=project.model_dump(mode="json"),
                ),
            )
            return project

    def restore(self, project_id: str, *, actor: str, target_path: str | None = None) -> Project:
        with self._lock:
            project = self._get(project_id)
            path = self._path(target_path if target_path is not None else project.target_path)
            self._ensure_unique_path(path, except_id=project.id)
            if project.status == ProjectStatus.ACTIVE and project.target_path == path:
                return project
            before = project.model_dump(mode="json")
            timestamp = now_iso()
            project.target_path = path
            project.status = ProjectStatus.ACTIVE
            project.archived_at = None
            project.updated_at = timestamp
            self._save(
                project,
                ProjectEvent(
                    project_id=project.id,
                    type="ProjectRestored",
                    actor=actor,
                    before=before,
                    after=project.model_dump(mode="json"),
                ),
            )
            return project

    def events(self, project_id: str) -> list[ProjectEvent]:
        self._get(project_id)
        return self._repo.list_project_events(project_id)

    def resolve_workspace(self, project_id: str, requested_path: str | None) -> str:
        """Resolve o snapshot de workspace usado por uma nova orquestração."""
        project = self._get(project_id)
        if project.status == ProjectStatus.ARCHIVED:
            raise ProjectConflictError("Projeto arquivado não aceita novas orquestrações.")
        if project.target_path is None:
            raise ProjectConflictError("Projeto sem pasta válida; restaure-o informando um path.")
        if requested_path is not None:
            canonical = self._path(requested_path)
            if canonical != project.target_path:
                raise ProjectConflictError(
                    "A pasta informada diverge da pasta canônica do projeto."
                )
        return project.target_path
