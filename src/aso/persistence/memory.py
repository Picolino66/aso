"""Adapter in-memory da porta OrchestrationRepository (default do MVP-1)."""

from __future__ import annotations

import threading
from typing import Any

from aso.agents.models import AgentDefinition
from aso.control.models import Orchestration, Project, ProjectEvent
from aso.control.routing_rules import RoutingRule
from aso.persistence.state import OrchestrationState


class InMemoryOrchestrationRepository:
    """Repositório volátil — não sobrevive ao processo. Útil para dev/testes."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def save(self, state: OrchestrationState) -> None:
        # Guarda como JSON para simular o mesmo ciclo serializa/desserializa do SQL.
        self._store[state.orchestration.id] = state.model_dump_json()

    def load(self, orchestration_id: str) -> OrchestrationState | None:
        blob = self._store.get(orchestration_id)
        if blob is None:
            return None
        return OrchestrationState.model_validate_json(blob)

    def list_ids(self) -> list[str]:
        return list(self._store.keys())

    def _all_states(self) -> list[OrchestrationState]:
        return [OrchestrationState.model_validate_json(b) for b in self._store.values()]

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
    ) -> tuple[list[Orchestration], int]:
        """Mesmo contrato de filtros baratos de `SqlAlchemyOrchestrationRepository`."""
        items = sorted((s.orchestration for s in self._all_states()), key=lambda o: o.created_at)
        if project_id is not None:
            items = [item for item in items if item.project_id == project_id]
        if status is not None:
            items = [item for item in items if item.status == status]
        if q:
            termo = q.lower()
            items = [item for item in items if termo in item.user_request.lower()]
        if executor is not None:
            items = [item for item in items if item.selected_executor == executor]
        if created_from is not None:
            items = [item for item in items if item.created_at >= created_from]
        if created_to is not None:
            items = [item for item in items if item.created_at <= created_to]
        total = len(items)
        sliced = items[offset : offset + limit] if limit is not None else items[offset:]
        return sliced, total

    def orchestration_ids_with_pending_approval(self) -> set[str]:
        """Mesmo contrato de
        `SqlAlchemyOrchestrationRepository.orchestration_ids_with_pending_approval`."""
        return {
            s.orchestration.id
            for s in self._all_states()
            for a in s.approvals
            if a.status == "pending"
        }

    def aggregate_metrics(self) -> dict[str, Any]:
        states = self._all_states()
        cards_by_status: dict[str, int] = {}
        adrs = snapshots = conflicts = retries = failures = 0
        for s in states:
            for card in s.cards:
                cards_by_status[card.status.value] = cards_by_status.get(card.status.value, 0) + 1
            adrs += len(s.adrs)
            snapshots += len(s.snapshots)
            conflicts += len([c for c in s.conflicts if c.status == "open"])
            for e in s.events:
                if e["type"] == "AgentRetry":
                    retries += 1
                elif e["type"] == "AgentFailed":
                    failures += 1
        return {
            "orchestrations_total": len(states),
            "cards_by_status": cards_by_status,
            "adrs_total": adrs,
            "snapshots_total": snapshots,
            "open_conflicts": conflicts,
            "agent_retries": retries,
            "agent_failures": failures,
        }

    def events_page(
        self, orchestration_id: str, *, limit: int, offset: int, newest_first: bool = False
    ) -> tuple[list[dict[str, Any]], int]:
        state = self.load(orchestration_id)
        if state is None:
            return [], 0
        eventos = list(reversed(state.events)) if newest_first else state.events
        return eventos[offset : offset + limit], len(state.events)

    def recent_events(self, *, limit: int) -> list[dict[str, Any]]:
        """Mesmo contrato de `SqlAlchemyOrchestrationRepository.recent_events`."""
        todos = [
            {**evento, "orchestration_id": s.orchestration.id}
            for s in self._all_states()
            for evento in s.events
        ]
        todos.sort(key=lambda e: str(e["created_at"]), reverse=True)
        return todos[:limit]

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
    ) -> tuple[list[dict[str, Any]], int]:
        """Mesmo contrato de filtros de `SqlAlchemyOrchestrationRepository.audit_page`."""
        itens: list[dict[str, Any]] = []
        for s in self._all_states():
            if project_id is not None and s.orchestration.project_id != project_id:
                continue
            if orchestration_id is not None and s.orchestration.id != orchestration_id:
                continue
            titulos = {c.id: c.title for c in s.cards}
            for evento in s.card_events:
                if agente is not None and evento.actor != agente:
                    continue
                if etapa is not None and evento.phase != etapa:
                    continue
                if resultado and resultado.lower() not in (evento.result or "").lower():
                    continue
                if data_de is not None and evento.created_at < data_de:
                    continue
                if data_ate is not None and evento.created_at > data_ate:
                    continue
                itens.append(
                    {
                        **evento.model_dump(mode="json"),
                        "orchestration_id": s.orchestration.id,
                        "project_id": s.orchestration.project_id,
                        "demanda": s.orchestration.user_request,
                        "card_titulo": titulos.get(evento.card_id, evento.card_id),
                    }
                )
        itens.sort(key=lambda i: str(i["created_at"]), reverse=True)
        total = len(itens)
        return itens[offset : offset + limit], total

    # --- consultas (computadas sobre o estado carregado) ---
    def cards_by_status(self, orchestration_id: str, status: str) -> list[str]:
        state = self.load(orchestration_id)
        if state is None:
            return []
        return [c.id for c in state.cards if c.status.value == status]

    def count_cards_by_status(self, orchestration_id: str) -> dict[str, int]:
        state = self.load(orchestration_id)
        if state is None:
            return {}
        counts: dict[str, int] = {}
        for card in state.cards:
            counts[card.status.value] = counts.get(card.status.value, 0) + 1
        return counts

    def adrs_by_status(self, orchestration_id: str, status: str) -> list[str]:
        state = self.load(orchestration_id)
        if state is None:
            return []
        return [a.id for a in state.adrs if a.status.value == status]

    def cards_linked_to_adr(self, orchestration_id: str, adr_id: str) -> list[str]:
        state = self.load(orchestration_id)
        if state is None:
            return []
        return [c.id for c in state.cards if adr_id in c.linked_adrs]


class InMemoryProjectRepository:
    """Adapter volátil e thread-safe do catálogo de projetos."""

    def __init__(self) -> None:
        self._projects: dict[str, str] = {}
        self._events: dict[str, list[str]] = {}
        self._lock = threading.RLock()

    def save_project(self, project: Project, event: ProjectEvent) -> None:
        with self._lock:
            current_raw = self._projects.get(project.id)
            if event.before:
                if current_raw is None:
                    raise ValueError("Projeto foi removido durante a operação.")
                current = Project.model_validate_json(current_raw)
                if current.model_dump(mode="json") != event.before:
                    raise ValueError("Projeto foi alterado por outra operação; recarregue-o.")
            elif current_raw is not None:
                raise ValueError("Projeto já existe.")
            for raw in self._projects.values():
                existing = Project.model_validate_json(raw)
                if existing.target_path == project.target_path and existing.id != project.id:
                    raise ValueError("A pasta já pertence a outro projeto.")
            self._projects[project.id] = project.model_dump_json()
            self._events.setdefault(project.id, []).append(event.model_dump_json())

    def get_project(self, project_id: str) -> Project | None:
        with self._lock:
            raw = self._projects.get(project_id)
            return Project.model_validate_json(raw) if raw is not None else None

    def get_project_by_path(self, target_path: str) -> Project | None:
        with self._lock:
            for raw in self._projects.values():
                project = Project.model_validate_json(raw)
                if project.target_path == target_path:
                    return project
            return None

    def list_projects(self, *, include_archived: bool = False) -> list[Project]:
        with self._lock:
            projects = [Project.model_validate_json(raw) for raw in self._projects.values()]
        if not include_archived:
            projects = [project for project in projects if project.status.value == "active"]
        return sorted(projects, key=lambda project: (project.name.lower(), project.created_at))

    def list_project_events(self, project_id: str) -> list[ProjectEvent]:
        with self._lock:
            return [
                ProjectEvent.model_validate_json(raw) for raw in self._events.get(project_id, [])
            ]


class InMemoryRoutingRuleRepository:
    """Adapter volátil e thread-safe das regras de roteamento (§33, ADR-0028)."""

    def __init__(self) -> None:
        self._rules: dict[str, str] = {}
        self._lock = threading.RLock()

    def save_rule(self, rule: RoutingRule, *, before_updated_at: str | None = None) -> None:
        with self._lock:
            current_raw = self._rules.get(rule.id)
            if before_updated_at is not None:
                if current_raw is None:
                    raise ValueError("Regra foi removida durante a operação.")
                current = RoutingRule.model_validate_json(current_raw)
                if current.updated_at != before_updated_at:
                    raise ValueError("Regra foi alterada por outra operação; recarregue-a.")
            self._rules[rule.id] = rule.model_dump_json()

    def get_rule(self, rule_id: str) -> RoutingRule | None:
        with self._lock:
            raw = self._rules.get(rule_id)
            return RoutingRule.model_validate_json(raw) if raw is not None else None

    def list_rules(self, *, only_active: bool = False) -> list[RoutingRule]:
        with self._lock:
            rules = [RoutingRule.model_validate_json(raw) for raw in self._rules.values()]
        if only_active:
            rules = [r for r in rules if r.ativa]
        return sorted(rules, key=lambda r: (r.precedencia, r.created_at))

    def delete_rule(self, rule_id: str) -> None:
        with self._lock:
            self._rules.pop(rule_id, None)


class InMemoryAgentDefinitionRepository:
    """Adapter volátil e thread-safe do catálogo de agentes (Tela 30, wf §32,
    ADR-0053) — mesmo desenho de `InMemoryRoutingRuleRepository`."""

    def __init__(self) -> None:
        self._definitions: dict[str, str] = {}
        self._lock = threading.RLock()

    def save_definition(
        self, definition: AgentDefinition, *, before_updated_at: str | None = None
    ) -> None:
        with self._lock:
            current_raw = self._definitions.get(definition.id)
            if before_updated_at is not None:
                if current_raw is None:
                    raise ValueError("Definição foi removida durante a operação.")
                current = AgentDefinition.model_validate_json(current_raw)
                if current.updated_at != before_updated_at:
                    raise ValueError("Definição foi alterada por outra operação; recarregue-a.")
            self._definitions[definition.id] = definition.model_dump_json()

    def get_definition(self, definition_id: str) -> AgentDefinition | None:
        with self._lock:
            raw = self._definitions.get(definition_id)
            return AgentDefinition.model_validate_json(raw) if raw is not None else None

    def list_definitions(self, *, only_active: bool = False) -> list[AgentDefinition]:
        with self._lock:
            definitions = [
                AgentDefinition.model_validate_json(raw) for raw in self._definitions.values()
            ]
        if only_active:
            definitions = [d for d in definitions if d.ativo]
        return sorted(definitions, key=lambda d: d.nome)

    def delete_definition(self, definition_id: str) -> None:
        with self._lock:
            self._definitions.pop(definition_id, None)
