"""EventLog append-only in-memory (observabilidade mínima — §33).

Registra eventos de domínio para timeline e auditoria. Um adapter persistente
(Postgres) substituirá o armazenamento in-memory em MVP posterior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aso.shared.ids import now_iso


@dataclass(frozen=True)
class DomainEvent:
    """Evento de domínio imutável."""

    type: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=now_iso)


class EventLog:
    """Log append-only de eventos de domínio."""

    def __init__(self) -> None:
        self._events: list[DomainEvent] = []

    def append(self, event_type: str, payload: dict[str, Any]) -> DomainEvent:
        event = DomainEvent(type=event_type, payload=payload)
        self._events.append(event)
        return event

    def seed(self, events: list[DomainEvent]) -> None:
        """Reidrata o log a partir de eventos persistidos."""
        self._events = list(events)

    def extend(self, events: list[DomainEvent]) -> None:
        """Anexa eventos (ex.: mesclar logs de execuções isoladas/concorrentes)."""
        self._events.extend(events)

    def all(self) -> list[DomainEvent]:
        return list(self._events)

    def of_type(self, event_type: str) -> list[DomainEvent]:
        return [e for e in self._events if e.type == event_type]
