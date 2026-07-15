"""Adapter in-memory da porta OrchestrationRepository (default do MVP-1)."""

from __future__ import annotations

import threading
from typing import Any

from aso.control.models import Orchestration, Project, ProjectEvent
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
        self, *, limit: int | None = None, offset: int = 0, project_id: str | None = None
    ) -> tuple[list[Orchestration], int]:
        items = sorted((s.orchestration for s in self._all_states()), key=lambda o: o.created_at)
        if project_id is not None:
            items = [item for item in items if item.project_id == project_id]
        total = len(items)
        sliced = items[offset : offset + limit] if limit is not None else items[offset:]
        return sliced, total

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
        self, orchestration_id: str, *, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        state = self.load(orchestration_id)
        if state is None:
            return [], 0
        return state.events[offset : offset + limit], len(state.events)

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
