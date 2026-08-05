"""Vestígios pequenos dos planos anteriores, fechados pela ADR-0022 (§4.7).

1. `SPEC_KEY` era um literal solto em `review.py`/`orchestration_service.py`: se os
   dois divergissem, a checagem determinística do §6 (testes/rollback obrigatórios)
   se desligaria em silêncio. Os testes aqui importam a CONSTANTE, não o literal —
   se `review.py` voltar a comparar contra `"especificacao"` hardcoded e alguém
   renomear `SPEC_KEY`, este teste quebra (é o ponto).
2. Card `Cancelled`/`Archived` não liberava dependentes — ficavam bloqueados para
   sempre, sem aviso. Agora bloqueia com motivo explícito: a dependência não foi
   satisfeita, foi abandonada.
"""

from __future__ import annotations

from aso.control.models import SPEC_KEY
from aso.control.review import VEREDITO_DOC_REPROVADO, ReviewService
from aso.control.spec import SpecDocument
from aso.control.triage import DemandBrief
from aso.kanban.board_service import BoardService
from aso.kanban.models import KanbanCard
from aso.shared.types import CardType, ColumnKey, Phase

# --------------------------------------------------------------------- SPEC_KEY


def test_checagem_deterministica_dispara_para_o_valor_de_spec_key() -> None:
    """Chama `revisar_documento` com a CONSTANTE, não o literal — prova que
    `review.py` compara contra o mesmo valor de `SPEC_KEY`, não um literal solto
    que poderia divergir dela sem teste vermelho."""
    doc = SpecDocument()  # sem estrategia_de_testes nem plano_de_rollback
    verdito = ReviewService(None).revisar_documento(
        None, documento=doc, tipo=SPEC_KEY, brief=DemandBrief()
    )
    assert verdito.veredito == VEREDITO_DOC_REPROVADO
    assert verdito.origem == "checagem_deterministica"


def test_checagem_deterministica_nao_dispara_para_outro_tipo_de_documento() -> None:
    """Controle: um tipo de documento diferente de `SPEC_KEY` não aciona a
    checagem de testes/rollback — ela é específica da especificação."""
    doc = SpecDocument()
    verdito = ReviewService(None).revisar_documento(
        None, documento=doc, tipo="discovery", brief=DemandBrief()
    )
    assert verdito.origem != "checagem_deterministica"


# -------------------------------------------------- Cancelled/Archived e dependentes


def _card(board_id: str, *, dependencies: list[str] | None = None) -> KanbanCard:
    return KanbanCard(
        board_id=board_id,
        orchestration_id="orch_x",
        phase=Phase.F5,
        type=CardType.TASK,
        title="card",
        dependencies=dependencies or [],
    )


def test_card_cancelado_bloqueia_dependente_com_motivo() -> None:
    svc = BoardService()
    board = svc.create_board("orch_x", "Board")
    base = svc.add_card(_card(board.id))
    dependente = svc.add_card(_card(board.id, dependencies=[base.id]))

    svc.move_card(base.id, ColumnKey.CANCELLED)

    atualizado = svc.get_card(dependente.id)
    assert atualizado is not None
    assert atualizado.status == ColumnKey.BLOCKED
    assert base.id in atualizado.blocked_by
    assert atualizado.block_reason and "cancelada" in atualizado.block_reason.lower()


def test_card_arquivado_bloqueia_dependente_com_motivo() -> None:
    svc = BoardService()
    board = svc.create_board("orch_x", "Board")
    base = svc.add_card(_card(board.id))
    dependente = svc.add_card(_card(board.id, dependencies=[base.id]))

    svc.move_card(base.id, ColumnKey.ARCHIVED)

    atualizado = svc.get_card(dependente.id)
    assert atualizado is not None
    assert atualizado.status == ColumnKey.BLOCKED
    assert atualizado.block_reason and "arquivada" in atualizado.block_reason.lower()


def test_card_terminal_nao_e_reaberto_por_dependencia_cancelada() -> None:
    """Um dependente que já chegou a `Done` não volta para `Blocked` — o
    observador só age sobre cards ainda em andamento."""
    svc = BoardService()
    board = svc.create_board("orch_x", "Board")
    base = svc.add_card(_card(board.id))
    dependente = svc.add_card(_card(board.id, dependencies=[base.id]))
    svc.move_card(dependente.id, ColumnKey.DONE)

    svc.move_card(base.id, ColumnKey.CANCELLED)

    assert svc.get_card(dependente.id).status == ColumnKey.DONE  # type: ignore[union-attr]


def test_card_done_continua_liberando_dependente_normalmente() -> None:
    """Regressão: `Done` continua satisfazendo a dependência (ADR-0021) — só
    `Cancelled`/`Archived` mudaram de comportamento."""
    svc = BoardService()
    board = svc.create_board("orch_x", "Board")
    base = svc.add_card(_card(board.id))
    dependente = svc.add_card(_card(board.id, dependencies=[base.id]))
    svc.move_card(dependente.id, ColumnKey.BLOCKED, reason="aguardando dependência(s): card")
    svc.get_card(dependente.id).blocked_by = [base.id]  # type: ignore[union-attr]

    svc.move_card(base.id, ColumnKey.DONE)

    assert svc.get_card(dependente.id).status == ColumnKey.READY  # type: ignore[union-attr]
