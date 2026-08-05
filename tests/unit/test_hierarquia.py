"""Hierarquia épico → história → subtarefa (§7 do fluxo.md, ADR-0025).

Profundidade máxima, ausência de ciclo e "pai não fecha antes dos filhos" são o
que torna `parent_id` útil em vez de decorativo — um caso por regra.
"""

from __future__ import annotations

import pytest

from aso.kanban.board_service import BoardService
from aso.kanban.hierarchy import fecha_ciclo, profundidade
from aso.kanban.models import KanbanCard
from aso.shared.types import CardType, ColumnKey, Phase

BOARD_ID = "board_h"


def _card(
    *, tipo: CardType = CardType.TASK, parent_id: str | None = None, **kwargs: object
) -> KanbanCard:
    base: dict[str, object] = {
        "board_id": BOARD_ID,
        "orchestration_id": "orch_h",
        "phase": Phase.F5,
        "type": tipo,
        "title": "card",
        "parent_id": parent_id,
    }
    base.update(kwargs)
    return KanbanCard(**base)  # type: ignore[arg-type]


def test_parent_id_nulo_continua_valido() -> None:
    """Todo card anterior a esta ADR não tem `parent_id` — precisa continuar funcionando."""
    svc = BoardService()
    card = svc.add_card(_card(title="legado"))
    assert card.parent_id is None


def test_profundidade_tres_aceita() -> None:
    svc = BoardService()
    epic = svc.add_card(_card(tipo=CardType.EPIC, title="Epic"))
    feature = svc.add_card(_card(tipo=CardType.FEATURE, title="Feature", parent_id=epic.id))
    task = svc.add_card(_card(tipo=CardType.TASK, title="Task", parent_id=feature.id))
    assert profundidade(svc._cards, task.id) == 3  # noqa: SLF001 — acesso interno em teste


def test_profundidade_quatro_recusa() -> None:
    svc = BoardService()
    epic = svc.add_card(_card(tipo=CardType.EPIC, title="Epic"))
    feature = svc.add_card(_card(tipo=CardType.FEATURE, title="Feature", parent_id=epic.id))
    task = svc.add_card(_card(tipo=CardType.TASK, title="Task", parent_id=feature.id))
    with pytest.raises(ValueError, match="profundidade"):
        svc.add_card(_card(title="Subtarefa demais", parent_id=task.id))


def test_parent_id_inexistente_recusa() -> None:
    svc = BoardService()
    with pytest.raises(ValueError, match="parent_id inexistente"):
        svc.add_card(_card(title="órfão", parent_id="card_fantasma"))


def test_fecha_ciclo_detecta_lacos() -> None:
    """Sem endpoint de reparentar hoje — testa a função pura diretamente
    (defesa também usada por `add_card`, que nunca vê ciclo na criação normal:
    um card novo nasce com id fresco, nunca ancestral de si mesmo)."""
    a = _card(title="a")
    b = _card(title="b", parent_id=a.id)
    cards = {a.id: a, b.id: b}
    # Reparentar A sob B fecharia o laço a→b→a.
    assert fecha_ciclo(cards, a.id, b.id) is True
    # Um terceiro card, sem relação nenhuma, não fecha ciclo.
    c = _card(title="c")
    cards[c.id] = c
    assert fecha_ciclo(cards, c.id, a.id) is False


def test_pai_com_filho_aberto_nao_vai_a_done() -> None:
    svc = BoardService()
    epic = svc.add_card(_card(tipo=CardType.EPIC, title="Epic"))
    svc.add_card(_card(tipo=CardType.TASK, title="Task", parent_id=epic.id))
    with pytest.raises(ValueError, match="subtarefa"):
        svc.move_card(epic.id, ColumnKey.DONE)


def test_pai_fecha_quando_todos_os_filhos_terminam() -> None:
    svc = BoardService()
    epic = svc.add_card(_card(tipo=CardType.EPIC, title="Epic"))
    filho = svc.add_card(_card(tipo=CardType.TASK, title="Task", parent_id=epic.id))
    svc.move_card(filho.id, ColumnKey.DONE)
    moved = svc.move_card(epic.id, ColumnKey.DONE)
    assert moved.status == ColumnKey.DONE


def test_filho_cancelado_tambem_libera_o_pai() -> None:
    svc = BoardService()
    epic = svc.add_card(_card(tipo=CardType.EPIC, title="Epic"))
    filho = svc.add_card(_card(tipo=CardType.TASK, title="Task", parent_id=epic.id))
    svc.move_card(filho.id, ColumnKey.CANCELLED)
    moved = svc.move_card(epic.id, ColumnKey.DONE)
    assert moved.status == ColumnKey.DONE


def test_cancelar_pai_cancela_filhos() -> None:
    svc = BoardService()
    epic = svc.add_card(_card(tipo=CardType.EPIC, title="Epic"))
    feature = svc.add_card(_card(tipo=CardType.FEATURE, title="Feature", parent_id=epic.id))
    task = svc.add_card(_card(tipo=CardType.TASK, title="Task", parent_id=feature.id))
    svc.move_card(epic.id, ColumnKey.CANCELLED)
    assert svc.get_card(feature.id).status == ColumnKey.CANCELLED  # type: ignore[union-attr]
    assert svc.get_card(task.id).status == ColumnKey.CANCELLED  # type: ignore[union-attr]


def test_cancelar_pai_nao_mexe_em_filho_ja_done() -> None:
    """Filho já `Done` fica como está — cancelar não desfaz trabalho concluído."""
    svc = BoardService()
    epic = svc.add_card(_card(tipo=CardType.EPIC, title="Epic"))
    filho = svc.add_card(_card(tipo=CardType.TASK, title="Task", parent_id=epic.id))
    svc.move_card(filho.id, ColumnKey.DONE)
    svc.move_card(epic.id, ColumnKey.CANCELLED)
    assert svc.get_card(filho.id).status == ColumnKey.DONE  # type: ignore[union-attr]
