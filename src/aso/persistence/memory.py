"""Adapter in-memory da porta OrchestrationRepository (default do MVP-1)."""

from __future__ import annotations

from typing import Any

from aso.control.models import Orchestration
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

    def delete(self, orchestration_id: str) -> None:
        self._store.pop(orchestration_id, None)

    def list_ids(self) -> list[str]:
        return list(self._store.keys())

    def _all_states(self) -> list[OrchestrationState]:
        return [OrchestrationState.model_validate_json(b) for b in self._store.values()]

    def list_orchestrations(
        self, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[Orchestration], int]:
        items = sorted((s.orchestration for s in self._all_states()), key=lambda o: o.created_at)
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
