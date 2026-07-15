"""Store de projetos (JSON file, similar ao ExecutorSettingsStore).

Persiste projetos com nome, descrição e caminho da pasta em `.aso/projects.json`.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from pydantic import BaseModel, Field

from aso.shared.ids import gen_id, now_iso


class Project(BaseModel):
    """Projeto agrupador de orquestrações (Kanban Macro)."""

    id: str = Field(default_factory=lambda: gen_id("proj"))
    name: str
    description: str = ""
    target_path: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ProjectStore:
    """Lê e persiste a lista de projetos em disco (thread-safe)."""

    def __init__(self, path: str | None = None) -> None:
        self._path = Path(path or os.environ.get("ASO_PROJECTS_FILE", ".aso/projects.json"))
        self._lock = threading.Lock()

    def load(self) -> list[Project]:
        with self._lock:
            if not self._path.exists():
                return []
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                return [Project.model_validate(item) for item in raw]
            except (json.JSONDecodeError, ValueError, OSError):
                return []

    def save(self, projects: list[Project]) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = [p.model_dump() for p in projects]
            self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, project: Project) -> Project:
        projects = self.load()
        projects.append(project)
        self.save(projects)
        return project

    def update(self, project: Project) -> Project | None:
        projects = self.load()
        for i, p in enumerate(projects):
            if p.id == project.id:
                project.updated_at = now_iso()
                projects[i] = project
                self.save(projects)
                return project
        return None

    def delete(self, project_id: str) -> bool:
        projects = self.load()
        new_list = [p for p in projects if p.id != project_id]
        if len(new_list) == len(projects):
            return False
        self.save(new_list)
        return True

    def get(self, project_id: str) -> Project | None:
        for p in self.load():
            if p.id == project_id:
                return p
        return None
