"""Porta de repositório de orquestrações (Ports & Adapters, ADR-0001/0006)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from aso.agents.models import AgentDefinition
from aso.control.models import Orchestration, Project, ProjectEvent
from aso.control.routing_rules import RoutingRule
from aso.persistence.state import OrchestrationState


@runtime_checkable
class OrchestrationRepository(Protocol):
    """Contrato de persistência do aggregate de orquestração."""

    def save(self, state: OrchestrationState) -> None: ...

    def load(self, orchestration_id: str) -> OrchestrationState | None: ...

    def list_ids(self) -> list[str]: ...

    # --- leitura leve / paginação / agregação (sem hidratar o aggregate) ---
    def list_orchestrations(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        project_id: str | None = None,
        status: str | None = None,
        q: str | None = None,
        executor: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> tuple[list[Orchestration], int]: ...

    def orchestration_ids_with_pending_approval(self) -> set[str]: ...

    def aggregate_metrics(self) -> dict[str, Any]: ...

    def events_page(
        self, orchestration_id: str, *, limit: int, offset: int, newest_first: bool = False
    ) -> tuple[list[dict[str, Any]], int]: ...

    def recent_events(self, *, limit: int) -> list[dict[str, Any]]: ...

    def audit_page(
        self,
        *,
        limit: int,
        offset: int,
        project_id: str | None = None,
        orchestration_id: str | None = None,
        agente: str | None = None,
        etapa: str | None = None,
        resultado: str | None = None,
        data_de: str | None = None,
        data_ate: str | None = None,
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


@runtime_checkable
class RoutingRuleRepository(Protocol):
    """Contrato de persistência das regras de roteamento (§33, ADR-0028)."""

    def save_rule(self, rule: RoutingRule, *, before_updated_at: str | None = None) -> None: ...

    def get_rule(self, rule_id: str) -> RoutingRule | None: ...

    def list_rules(self, *, only_active: bool = False) -> list[RoutingRule]: ...

    def delete_rule(self, rule_id: str) -> None: ...


@runtime_checkable
class AgentDefinitionRepository(Protocol):
    """Contrato de persistência do catálogo de agentes (Tela 30, wf §32, ADR-0053)."""

    def save_definition(
        self, definition: AgentDefinition, *, before_updated_at: str | None = None
    ) -> None: ...

    def get_definition(self, definition_id: str) -> AgentDefinition | None: ...

    def list_definitions(self, *, only_active: bool = False) -> list[AgentDefinition]: ...

    def delete_definition(self, definition_id: str) -> None: ...
