"""Auditoria de movimentação — §8 do fluxo.md, pendência da ADR-0018 fechada na
ADR-0019: cada movimentação registra motivo, resultado, evidências e próxima ação."""

from __future__ import annotations

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


def test_move_card_grava_reason_no_evento_nao_so_em_block_reason() -> None:
    svc = BoardService()
    board = svc.create_board("orch_x", "Board MVP")
    card = svc.add_card(_card(board.id))

    svc.move_card(card.id, ColumnKey.IN_PROGRESS, reason="agente começou")

    evento = svc.card_events[-1]
    assert evento.reason == "agente começou"
    # Coluna != Blocked: block_reason do card não é tocado por este caminho.
    assert svc.get_card(card.id).block_reason is None  # type: ignore[union-attr]


def test_move_card_grava_result_e_evidence_e_next_action() -> None:
    svc = BoardService()
    board = svc.create_board("orch_x", "Board MVP")
    card = svc.add_card(_card(board.id))

    svc.move_card(
        card.id,
        ColumnKey.TESTING,
        reason="execução concluída",
        result="diff aplicado sem pendências",
        evidence=["branch=feat/x", "diff_lines=12"],
        next_action="abrir PR",
    )

    evento = svc.card_events[-1]
    assert evento.result == "diff aplicado sem pendências"
    assert evento.evidence == ["branch=feat/x", "diff_lines=12"]
    assert evento.next_action == "abrir PR"


def test_apply_event_preenche_result_e_next_action_a_partir_da_transicao() -> None:
    svc = BoardService()
    board = svc.create_board("orch_x", "Board MVP")
    card = svc.add_card(_card(board.id))

    svc.apply_event(card.id, "PROpened")

    evento = svc.card_events[-1]
    assert evento.to_status == ColumnKey.REVIEW
    assert evento.result
    assert evento.next_action


def test_ci_failed_agora_transiciona_para_needs_fix_com_resultado() -> None:
    """CI reprovada é corrigível (ADR-0019): `NeedsFix`, não `Failed`."""
    svc = BoardService()
    board = svc.create_board("orch_x", "Board MVP")
    card = svc.add_card(_card(board.id))

    svc.apply_event(card.id, "CIFailed")

    assert svc.get_card(card.id).status == ColumnKey.NEEDS_FIX  # type: ignore[union-attr]
    evento = svc.card_events[-1]
    assert "CI" in evento.result or "ci" in evento.result.lower()
    assert evento.next_action


def test_evidence_default_vazio_quando_nao_informado() -> None:
    svc = BoardService()
    board = svc.create_board("orch_x", "Board MVP")
    card = svc.add_card(_card(board.id))

    svc.move_card(card.id, ColumnKey.BLOCKED, reason="conflito")

    evento = svc.card_events[-1]
    assert evento.evidence == []
    assert evento.reason == "conflito"
    assert svc.get_card(card.id).block_reason == "conflito"  # type: ignore[union-attr]
