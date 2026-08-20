"""Ficha completa de um card (Tela 12, wf §14) — ADR-0041."""

from __future__ import annotations

import pytest

from aso.control.orchestration_service import OrchestrationService
from aso.shared.types import CardType


def test_get_card_devolve_ficha_completa() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda", seed_cards=False)
    criado = svc.create_card(orch.id, title="Login OAuth", type=CardType.TASK)

    card = svc.get_card(orch.id, criado.id)

    assert card.id == criado.id
    assert card.title == "Login OAuth"
    assert card.type == CardType.TASK


def test_get_card_inexistente_leva_a_keyerror() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda", seed_cards=False)
    with pytest.raises(KeyError, match="Card inexistente"):
        svc.get_card(orch.id, "card_fantasma")


def test_get_card_events_vazio_para_card_recem_criado() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda", seed_cards=False)
    card = svc.create_card(orch.id, title="Login OAuth")
    assert svc.get_card_events(orch.id, card.id) == []


def test_get_card_events_registra_movimentacoes_sem_truncar() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda", seed_cards=False)
    card = svc.create_card(orch.id, title="Login OAuth")

    b = svc._bundle(orch.id)  # noqa: SLF001 — teste inspeciona o bundle diretamente
    from aso.shared.types import ColumnKey

    for destino in (ColumnKey.READY, ColumnKey.PLANNING, ColumnKey.IN_PROGRESS):
        b.board_service.move_card(card.id, destino, actor="tester", reason="avanço manual")

    eventos = svc.get_card_events(orch.id, card.id)
    assert len(eventos) == 3
    assert eventos[0].to_status == ColumnKey.READY
    assert eventos[-1].to_status == ColumnKey.IN_PROGRESS
    assert all(e.card_id == card.id for e in eventos)


def test_get_card_events_nao_mistura_cards_diferentes() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda", seed_cards=False)
    a = svc.create_card(orch.id, title="Card A")
    b_card = svc.create_card(orch.id, title="Card B")

    b = svc._bundle(orch.id)  # noqa: SLF001
    from aso.shared.types import ColumnKey

    b.board_service.move_card(a.id, ColumnKey.READY, actor="tester")

    assert len(svc.get_card_events(orch.id, a.id)) == 1
    assert svc.get_card_events(orch.id, b_card.id) == []


def test_get_card_events_inexistente_leva_a_keyerror() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda", seed_cards=False)
    with pytest.raises(KeyError, match="Card inexistente"):
        svc.get_card_events(orch.id, "card_fantasma")
