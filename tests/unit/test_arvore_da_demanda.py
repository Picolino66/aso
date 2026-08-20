"""Árvore da demanda (Tela 10, wf §12) — ADR-0040."""

from __future__ import annotations

import pytest

from aso.control.orchestration_service import OrchestrationService
from aso.kanban.hierarchy import montar_arvore
from aso.kanban.models import KanbanCard
from aso.shared.types import CardType, Phase


def _card(
    *, tipo: CardType = CardType.TASK, parent_id: str | None = None, **kw: object
) -> KanbanCard:
    base: dict[str, object] = {
        "board_id": "board_x",
        "orchestration_id": "orch_x",
        "phase": Phase.F5,
        "type": tipo,
        "title": "card",
        "parent_id": parent_id,
    }
    base.update(kw)
    return KanbanCard(**base)  # type: ignore[arg-type]


def test_montar_arvore_agrupa_raizes_e_filhos() -> None:
    epic = _card(tipo=CardType.EPIC, title="Epic")
    feature = _card(tipo=CardType.FEATURE, title="Feature", parent_id=epic.id)
    task = _card(tipo=CardType.TASK, title="Task", parent_id=feature.id)
    cards = {c.id: c for c in (epic, feature, task)}

    arvore = montar_arvore(cards)

    assert len(arvore) == 1
    assert arvore[0]["id"] == epic.id
    assert arvore[0]["title"] == "Epic"
    assert len(arvore[0]["filhos"]) == 1
    assert arvore[0]["filhos"][0]["id"] == feature.id
    assert arvore[0]["filhos"][0]["filhos"][0]["id"] == task.id
    assert arvore[0]["filhos"][0]["filhos"][0]["filhos"] == []


def test_montar_arvore_cards_sem_pai_sao_todos_raizes() -> None:
    a = _card(title="a")
    b = _card(title="b")
    cards = {a.id: a, b.id: b}
    arvore = montar_arvore(cards)
    assert {n["id"] for n in arvore} == {a.id, b.id}


def test_montar_arvore_vazia() -> None:
    assert montar_arvore({}) == []


# ------------------------------------------------------------- service-level


def test_get_card_tree_via_service() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda", seed_cards=False)
    epic = svc.create_card(orch.id, title="Autenticação OAuth", type=CardType.EPIC)
    svc.create_card(orch.id, title="Login", type=CardType.FEATURE, parent_id=epic.id)

    arvore = svc.get_card_tree(orch.id)
    assert len(arvore) == 1
    assert arvore[0]["title"] == "Autenticação OAuth"
    assert len(arvore[0]["filhos"]) == 1
    assert arvore[0]["filhos"][0]["title"] == "Login"


def test_create_card_respeita_hierarquia() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda", seed_cards=False)
    epic = svc.create_card(orch.id, title="Epic", type=CardType.EPIC)
    card = svc.create_card(orch.id, title="Feature", type=CardType.FEATURE, parent_id=epic.id)
    assert card.parent_id == epic.id
    assert card.type == CardType.FEATURE


def test_create_card_com_parent_inexistente_leva_a_valueerror() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda", seed_cards=False)
    with pytest.raises(ValueError, match="parent_id inexistente"):
        svc.create_card(orch.id, title="órfão", parent_id="card_fantasma")


def test_create_card_alem_da_profundidade_maxima_leva_a_valueerror() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda", seed_cards=False)
    epic = svc.create_card(orch.id, title="Epic", type=CardType.EPIC)
    feature = svc.create_card(orch.id, title="Feature", type=CardType.FEATURE, parent_id=epic.id)
    task = svc.create_card(orch.id, title="Task", parent_id=feature.id)
    subtarefa = svc.create_card(orch.id, title="Subtarefa", parent_id=task.id)
    with pytest.raises(ValueError, match="profundidade"):
        svc.create_card(orch.id, title="Além da subtarefa", parent_id=subtarefa.id)
