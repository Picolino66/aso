"""Testes do Kanban Plane (TASK-04)."""

from __future__ import annotations

import pytest

from aso.kanban.board_service import BoardService
from aso.kanban.models import KanbanCard
from aso.shared.types import CardType, ColumnKey, Phase


def _card(board_id: str) -> KanbanCard:
    return KanbanCard(
        board_id=board_id,
        orchestration_id="orch_x",
        phase=Phase.F5,
        type=CardType.TASK,
        title="Implementar X",
    )


def test_create_board_has_default_columns() -> None:
    svc = BoardService()
    board = svc.create_board("orch_x", "Board MVP")
    assert len(board.columns) == 12
    assert board.columns[0].key == ColumnKey.BACKLOG


def test_move_card_records_event() -> None:
    svc = BoardService()
    board = svc.create_board("orch_x", "Board MVP")
    card = svc.add_card(_card(board.id))
    svc.move_card(card.id, ColumnKey.IN_PROGRESS)
    assert svc.get_card(card.id).status == ColumnKey.IN_PROGRESS  # type: ignore[union-attr]
    assert svc.card_events[-1].to_status == ColumnKey.IN_PROGRESS


def test_apply_event_automation() -> None:
    svc = BoardService()
    board = svc.create_board("orch_x", "Board MVP")
    card = svc.add_card(_card(board.id))
    svc.apply_event(card.id, "AgentStarted")
    assert svc.get_card(card.id).status == ColumnKey.IN_PROGRESS  # type: ignore[union-attr]
    svc.apply_event(card.id, "QualityGatePassed")
    assert svc.get_card(card.id).status == ColumnKey.DONE  # type: ignore[union-attr]


def test_apply_unknown_event_raises() -> None:
    svc = BoardService()
    board = svc.create_board("orch_x", "Board MVP")
    card = svc.add_card(_card(board.id))
    with pytest.raises(KeyError):
        svc.apply_event(card.id, "EventoInexistente")


def test_block_records_reason() -> None:
    svc = BoardService()
    board = svc.create_board("orch_x", "Board MVP")
    card = svc.add_card(_card(board.id))
    svc.move_card(card.id, ColumnKey.BLOCKED, reason="dependência pendente")
    assert svc.get_card(card.id).block_reason == "dependência pendente"  # type: ignore[union-attr]
