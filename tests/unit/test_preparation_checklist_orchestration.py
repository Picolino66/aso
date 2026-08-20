"""Checklist de preparação + tarefa vinculada via `OrchestrationService` (§10, ADR-0030).

Cobre: marcação automática dos itens em `run_card`/`run_plan` (caminhos
compartilhados por `_build_task`), criação idempotente da tarefa vinculada no
bloqueio por dependência, limpeza do ponteiro ao desbloquear, e a evidência no
encerramento do card (§23).
"""

from __future__ import annotations

import pytest

from aso.control.decision_engine import MultiAgentDecisionEngine
from aso.control.models import DecisionInput, MultiAgentDecision, PlannedAgent
from aso.control.orchestration_service import OrchestrationService
from aso.control.preparation import (
    ITEM_CARD_DESBLOQUEADO,
    ITEM_DEPENDENCIAS_VERIFICADAS,
    ITENS_CHECKLIST_PREPARACAO,
)
from aso.shared.types import CardType, ColumnKey, ExecutionStrategy, RiskLevel

_DIN_MULTIDOMINIO = DecisionInput(
    user_request="implementar recurso seguro",
    domains=["backend", "security"],
    risk_level=RiskLevel.HIGH,
    parallelizable=True,
    needs_independent_review=True,
    impacts=["security"],
)


def _criar_com_dependencia(svc: OrchestrationService) -> tuple[str, str, list[str]]:
    orch = svc.create_orchestration("implementar recurso seguro", decision_input=_DIN_MULTIDOMINIO)
    cards = svc.get_cards(orch.id)
    review_card = next(c for c in cards if c.assignee == "ReviewAgent")
    workers = [c for c in cards if c.assignee != "ReviewAgent"]
    return orch.id, review_card.id, [w.id for w in workers]


# --------------------------------------------------------------------- run_card


def test_run_card_marca_itens_de_entrega_de_contexto() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("ajustar relatorio mensal de vendas")
    card = svc.get_cards(orch.id)[0]

    svc.run_card(orch.id, card.id)

    atualizado = next(c for c in svc.get_cards(orch.id) if c.id == card.id)
    itens = {c["item"] for c in atualizado.preparation_checklist}
    # Os 5 itens de "entrega de contexto" + dependências/desbloqueado (sem
    # dependência real aqui) — branch depende do provider produzir artifact.
    assert ITEM_DEPENDENCIAS_VERIFICADAS in itens
    assert ITEM_CARD_DESBLOQUEADO in itens
    assert len(itens) >= 5


def test_run_card_bloqueado_cria_tarefa_vinculada_uma_unica_vez() -> None:
    svc = OrchestrationService()
    orch_id, review_id, _worker_ids = _criar_com_dependencia(svc)

    with pytest.raises(ValueError):
        svc.run_card(orch_id, review_id)

    card = next(c for c in svc.get_cards(orch_id) if c.id == review_id)
    assert card.dependency_task_id is not None
    primeira_tarefa_id = card.dependency_task_id

    tarefas = [c for c in svc.get_cards(orch_id) if c.id == primeira_tarefa_id]
    assert len(tarefas) == 1
    tarefa = tarefas[0]
    assert tarefa.type == CardType.TASK
    assert tarefa.status == ColumnKey.BACKLOG
    assert card.title in tarefa.title

    # Segunda tentativa (dependência ainda pendente) não cria uma segunda tarefa.
    with pytest.raises(ValueError):
        svc.run_card(orch_id, review_id)
    card2 = next(c for c in svc.get_cards(orch_id) if c.id == review_id)
    assert card2.dependency_task_id == primeira_tarefa_id
    total_tarefas_vinculadas = [
        c for c in svc.get_cards(orch_id) if "Resolver dependência" in c.title
    ]
    assert len(total_tarefas_vinculadas) == 1


def test_desbloquear_limpa_o_ponteiro_da_tarefa_vinculada() -> None:
    svc = OrchestrationService()
    orch_id, review_id, worker_ids = _criar_com_dependencia(svc)

    with pytest.raises(ValueError):
        svc.run_card(orch_id, review_id)

    b = svc._bundle(orch_id)  # noqa: SLF001
    for wid in worker_ids:
        b.board_service.move_card(wid, ColumnKey.DONE)

    svc.run_card(orch_id, review_id)

    card = next(c for c in svc.get_cards(orch_id) if c.id == review_id)
    assert card.dependency_task_id is None
    itens = {c["item"] for c in card.preparation_checklist}
    assert ITEM_CARD_DESBLOQUEADO in itens


def test_card_sem_dependencia_nunca_ganha_tarefa_vinculada() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("ajustar relatorio mensal de vendas")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)
    atualizado = next(c for c in svc.get_cards(orch.id) if c.id == card.id)
    assert atualizado.dependency_task_id is None


# --------------------------------------------------------------------- run_plan


def test_run_plan_tambem_marca_o_checklist() -> None:
    """run_plan chama _build_task/_apply_execution — mesmo ponto de marcação de
    run_card, sem passar pelo guard de dependência (ADR-0018)."""
    svc = OrchestrationService()
    orch = svc.create_orchestration("ajustar relatorio mensal de vendas")
    card = svc.get_cards(orch.id)[0]

    svc.run_plan(orch.id)

    atualizado = next(c for c in svc.get_cards(orch.id) if c.id == card.id)
    itens = {c["item"] for c in atualizado.preparation_checklist}
    assert len(itens) >= 5


# ------------------------------------------------------------------ get_preparation_checklist


def test_get_preparation_checklist_devolve_o_checklist_do_card() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("ajustar relatorio mensal de vendas")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)

    checklist = svc.get_preparation_checklist(orch.id, card.id)
    assert len(checklist) >= 5
    assert all(item["item"] in ITENS_CHECKLIST_PREPARACAO for item in checklist)


def test_get_preparation_checklist_card_inexistente_levanta() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("ajustar relatorio mensal de vendas")
    with pytest.raises(KeyError):
        svc.get_preparation_checklist(orch.id, "card_inexistente")


def test_dependencia_orfa_nao_quebra_o_checklist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regressão do caminho já coberto por test_card_dependencies — confirma que a
    marcação nova não interfere na tolerância a dependência órfã."""

    def _decide_com_dependencia_orfa(
        self: MultiAgentDecisionEngine, inp: DecisionInput
    ) -> MultiAgentDecision:
        return MultiAgentDecision(
            execution_mode=ExecutionStrategy.SEQUENTIAL,
            reason="teste",
            risk_level=RiskLevel.LOW,
            agents=[
                PlannedAgent(
                    agent="BackendDevelopmentAgent", role="primary", depends_on=["AgenteFantasma"]
                )
            ],
        )

    monkeypatch.setattr(MultiAgentDecisionEngine, "decide", _decide_com_dependencia_orfa)
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)
    atualizado = next(c for c in svc.get_cards(orch.id) if c.id == card.id)
    assert atualizado.dependency_task_id is None
