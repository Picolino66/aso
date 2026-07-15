"""Porta de repositório de orquestrações (Ports & Adapters, ADR-0001/0006)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from aso.control.models import Orchestration, Project, ProjectEvent
from aso.persistence.state import OrchestrationState


@runtime_checkable
class OrchestrationRepository(Protocol):
    """Contrato de persistência do aggregate de orquestração."""

    def save(self, state: OrchestrationState) -> None: ...

    def load(self, orchestration_id: str) -> OrchestrationState | None: ...

    def list_ids(self) -> list[str]: ...

    # --- leitura leve / paginação / agregação (sem hidratar o aggregate) ---
    def list_orchestrations(
        self, *, limit: int | None = None, offset: int = 0, project_id: str | None = None
    ) -> tuple[list[Orchestration], int]: ...

    def aggregate_metrics(self) -> dict[str, Any]: ...

    def events_page(
        self, orchestration_id: str, *, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]: ...

    # --- consultas (lado de leitura / CQRS-lite) ---
    def cards_by_status(self, orchestration_id: str, status: str) -> list[str]: ...

    def count_cards_by_status(self, orchestration_id: str) -> dict[str, int]: ...

    def adrs_by_status(self, orchestration_id: str, status: str) -> list[str]: ...

    def cards_linked_to_adr(self, orchestration_id: str, adr_id: str) -> list[str]: ...


@runtime_checkable
class ProjectRepository(Protocol):
    """Contrato de persistência do catálogo de projetos e sua auditoria."""

    def save_project(self, project: Project, event: ProjectEvent) -> None: ...

    def get_project(self, project_id: str) -> Project | None: ...

    def get_project_by_path(self, target_path: str) -> Project | None: ...

    def list_projects(self, *, include_archived: bool = False) -> list[Project]: ...

    def list_project_events(self, project_id: str) -> list[ProjectEvent]: ...
