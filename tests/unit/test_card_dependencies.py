"""Ativação de `dependencies`/`blocked_by` no card (§10 do fluxo.md, ADR-0018).

Cobre só o caminho manual (`run_card`): o `run_plan` já ordena agentes pelas suas
próprias ondas (`PlannedAgent.depends_on`) e não é afetado por este guard.
"""

from __future__ import annotations

import pytest

from aso.application.orchestration_service import OrchestrationService
from aso.control.decision_engine import MultiAgentDecisionEngine
from aso.control.models import DecisionInput, MultiAgentDecision, PlannedAgent
from aso.shared.types import ColumnKey, ExecutionStrategy, RiskLevel

_DIN_MULTIDOMINIO = DecisionInput(
    user_request="implementar recurso seguro",
    domains=["backend", "security"],
    risk_level=RiskLevel.HIGH,
    parallelizable=True,
    needs_independent_review=True,
    impacts=["security"],
)


def _equipe_com_dependente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Equipe do plano com dependência real: um TestingAgent depende dos workers. O motor não
    cria mais o card do ReviewAgent (ADR-0075); a dependência vem do plano do mesmo jeito."""
    original = MultiAgentDecisionEngine._build_team

    def _com_dependente(
        self: MultiAgentDecisionEngine, inp: DecisionInput, strategy: ExecutionStrategy
    ) -> list[PlannedAgent]:
        equipe = original(self, inp, strategy)
        dependente = PlannedAgent(
            agent="TestingAgent",
            role="reviewer",
            reason="valida a entrega dos workers",
            depends_on=[a.agent for a in equipe],
        )
        return [*equipe, dependente]

    monkeypatch.setattr(MultiAgentDecisionEngine, "_build_team", _com_dependente)


def _criar_com_dependencia(
    svc: OrchestrationService, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str, list[str]]:
    _equipe_com_dependente(monkeypatch)
    orch = svc.create_orchestration("implementar recurso seguro", decision_input=_DIN_MULTIDOMINIO)
    cards = svc.get_cards(orch.id)
    dependente = next(c for c in cards if c.assignee == "TestingAgent")
    workers = [c for c in cards if c.assignee != "TestingAgent"]
    return orch.id, dependente.id, [w.id for w in workers]


def test_dependencies_populadas_a_partir_do_plano(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = OrchestrationService()
    orch_id, review_id, worker_ids = _criar_com_dependencia(svc, monkeypatch)
    review_card = next(c for c in svc.get_cards(orch_id) if c.id == review_id)
    assert set(review_card.dependencies) == set(worker_ids)
    # Workers não têm dependência entre si (paralelos).
    for wid in worker_ids:
        worker = next(c for c in svc.get_cards(orch_id) if c.id == wid)
        assert worker.dependencies == []


def test_run_card_recusa_com_dependencia_pendente(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = OrchestrationService()
    orch_id, review_id, worker_ids = _criar_com_dependencia(svc, monkeypatch)

    with pytest.raises(ValueError, match="dependência"):
        svc.run_card(orch_id, review_id)

    card = next(c for c in svc.get_cards(orch_id) if c.id == review_id)
    assert card.status == ColumnKey.BLOCKED
    assert set(card.blocked_by) == set(worker_ids)
    assert card.block_reason and "dependência" in card.block_reason


def test_run_card_funciona_apos_dependencias_resolvidas(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = OrchestrationService()
    orch_id, review_id, worker_ids = _criar_com_dependencia(svc, monkeypatch)

    with pytest.raises(ValueError):
        svc.run_card(orch_id, review_id)

    b = svc._bundle(orch_id)  # noqa: SLF001
    for wid in worker_ids:
        b.board_service.move_card(wid, ColumnKey.DONE)

    resultado = svc.run_card(orch_id, review_id)  # não deve levantar

    assert resultado is not None
    card = next(c for c in svc.get_cards(orch_id) if c.id == review_id)
    assert card.blocked_by == []


def test_card_sem_dependencias_nao_e_afetado() -> None:
    """Regressão: o guard novo não muda o comportamento de um card sem dependência."""
    svc = OrchestrationService()
    orch = svc.create_orchestration("ajustar relatorio mensal de vendas")
    card = svc.get_cards(orch.id)[0]
    assert card.dependencies == []

    resultado = svc.run_card(orch.id, card.id)

    assert resultado is not None
    card_depois = svc.get_cards(orch.id)[0]
    assert card_depois.status != ColumnKey.BLOCKED


def test_dependencia_para_agente_fora_do_plano_e_ignorada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensivo: `depends_on` que não bate com nenhum agente desta estratégia não
    quebra a criação — só é descartado (ex.: agente descartado pelo motor de decisão)."""

    def _decide_com_dependencia_orfa(
        self: MultiAgentDecisionEngine, inp: DecisionInput
    ) -> MultiAgentDecision:
        return MultiAgentDecision(
            execution_mode=ExecutionStrategy.SEQUENTIAL,
            reason="teste",
            risk_level=RiskLevel.LOW,
            agents=[
                PlannedAgent(
                    agent="BackendDevelopmentAgent",
                    role="primary",
                    depends_on=["AgenteFantasma"],
                )
            ],
        )

    monkeypatch.setattr(MultiAgentDecisionEngine, "decide", _decide_com_dependencia_orfa)
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    assert card.dependencies == []
