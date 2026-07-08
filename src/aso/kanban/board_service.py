"""BoardService (§16, TASK-04).

Cria boards com as colunas padrão, gerencia cards e aplica a automação de
movimentação dirigida por eventos (§16.7). Kanban é o plano de execução (ADR-0002).
"""

from __future__ import annotations

from aso.kanban.models import Board, BoardColumn, CardEvent, KanbanCard
from aso.shared.events import EventLog
from aso.shared.ids import now_iso
from aso.shared.types import ColumnKey

# Colunas padrão na ordem canônica (§16.2).
_DEFAULT_COLUMNS: list[ColumnKey] = [
    ColumnKey.BACKLOG,
    ColumnKey.READY,
    ColumnKey.PLANNING,
    ColumnKey.IN_PROGRESS,
    ColumnKey.WAITING_AGENT,
    ColumnKey.WAITING_HUMAN,
    ColumnKey.REVIEW,
    ColumnKey.TESTING,
    ColumnKey.BLOCKED,
    ColumnKey.FAILED,
    ColumnKey.DONE,
    ColumnKey.ARCHIVED,
]

# Automação: evento de runtime -> coluna destino (§16.7).
_EVENT_TRANSITIONS: dict[str, ColumnKey] = {
    "AgentStarted": ColumnKey.IN_PROGRESS,
    "AgentNeedsInput": ColumnKey.WAITING_HUMAN,
    "PROpened": ColumnKey.REVIEW,
    "CIFailed": ColumnKey.FAILED,
    "ReviewRequestedChanges": ColumnKey.REVIEW,
    "TestsPassed": ColumnKey.TESTING,
    "QualityGatePassed": ColumnKey.DONE,
    "QualityGateFailed": ColumnKey.BLOCKED,
}


class BoardService:
    """Serviço in-memory de boards e cards de uma orquestração."""

    def __init__(self, event_log: EventLog | None = None) -> None:
        self._boards: dict[str, Board] = {}
        self._cards: dict[str, KanbanCard] = {}
        self.card_events: list[CardEvent] = []
        self.event_log = event_log or EventLog()

    def create_board(
        self, orchestration_id: str, name: str, project_id: str | None = None
    ) -> Board:
        columns = [BoardColumn(key=key, order=i + 1) for i, key in enumerate(_DEFAULT_COLUMNS)]
        board = Board(
            orchestration_id=orchestration_id, project_id=project_id, name=name, columns=columns
        )
        self._boards[board.id] = board
        return board

    def hydrate(
        self, boards: list[Board], cards: list[KanbanCard], card_events: list[CardEvent]
    ) -> None:
        """Reidrata o serviço a partir de estado persistido."""
        self._boards = {b.id: b for b in boards}
        self._cards = {c.id: c for c in cards}
        self.card_events = list(card_events)

    def get_board(self, board_id: str) -> Board | None:
        return self._boards.get(board_id)

    def add_card(self, card: KanbanCard) -> KanbanCard:
        self._cards[card.id] = card
        self.event_log.append("CardCreated", {"card_id": card.id, "title": card.title})
        return card

    def get_card(self, card_id: str) -> KanbanCard | None:
        return self._cards.get(card_id)

    def cards_of(self, board_id: str) -> list[KanbanCard]:
        return [c for c in self._cards.values() if c.board_id == board_id]

    def move_card(
        self,
        card_id: str,
        to_status: ColumnKey,
        *,
        actor: str = "system",
        reason: str | None = None,
    ) -> KanbanCard:
        card = self._cards[card_id]
        from_status = card.status
        card.status = to_status
        card.updated_at = now_iso()
        if to_status == ColumnKey.BLOCKED and reason:
            card.block_reason = reason
        event = CardEvent(
            card_id=card_id,
            type="CardMoved",
            from_status=from_status,
            to_status=to_status,
            actor=actor,
        )
        self.card_events.append(event)
        self.event_log.append(
            "CardMoved",
            {"card_id": card_id, "from": from_status.value, "to": to_status.value},
        )
        return card

    def apply_event(self, card_id: str, event_name: str) -> KanbanCard:
        """Aplica a automação de coluna a partir de um evento de runtime (§16.7)."""
        to_status = _EVENT_TRANSITIONS.get(event_name)
        if to_status is None:
            raise KeyError(f"Evento sem transição automática definida: {event_name}")
        return self.move_card(card_id, to_status, actor="automation")
