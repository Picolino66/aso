"""MEL-11 — aprovação de estratégia pendente bloqueia a execução (regra inviolável 4).

Os testes tentam explicitamente executar a estratégia crítica sem decisão humana, por
todas as portas de entrada, e contam as chamadas ao provider para provar que nenhum
agente foi acionado.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aso.agents.executor import LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.api.app import create_app
from aso.control.models import DecisionInput
from aso.control.orchestration_service import OrchestrationService

_CRITICA = DecisionInput(user_request="deploy", domains=["devops"], impacts=["deploy"])


class _ProviderContador(LocalMockExecutionProvider):
    """Mock determinístico que conta quantas vezes um agente foi acionado."""

    def __init__(self) -> None:
        self.chamadas = 0

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        self.chamadas += 1
        return super().execute(agent, task)


def _cenario(tmp_path: Path | None = None) -> tuple[OrchestrationService, _ProviderContador, str]:
    provider = _ProviderContador()
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration(
        "deploy em produção",
        decision_input=_CRITICA,
        target_path=str(tmp_path) if tmp_path is not None else None,
    )
    return svc, provider, orch.id


def _estrategia(svc: OrchestrationService, oid: str) -> str:
    return next(a.id for a in svc.list_approvals(oid) if a.tipo == "estrategia")


def _um_card(svc: OrchestrationService, oid: str) -> str:
    b = svc._bundle(oid)  # noqa: SLF001 - só para achar um card executável
    return next(c.id for c in b.board_service.cards_of(b.board.id) if c.assignee)


def test_cenario_critico_abre_aprovacao_de_estrategia_pendente() -> None:
    svc, _p, oid = _cenario()
    assert [a.status for a in svc.list_approvals(oid) if a.tipo == "estrategia"] == ["pending"]


@pytest.mark.parametrize(
    "entrada",
    ["run_card", "run_plan", "run_phase", "race_card", "start_autopilot"],
)
def test_pendencia_recusa_todas_as_entradas_sem_chamar_agente(entrada: str) -> None:
    svc, provider, oid = _cenario()
    card_id = _um_card(svc, oid)
    chamadas = {
        "run_card": lambda: svc.run_card(oid, card_id),
        "run_plan": lambda: svc.run_plan(oid),
        "run_phase": lambda: svc.run_phase(oid),
        "race_card": lambda: svc.race_card(oid, card_id, [provider]),
        "start_autopilot": lambda: svc.start_autopilot(oid),
    }
    with pytest.raises(ValueError, match="aguardando aprovação humana"):
        chamadas[entrada]()
    assert provider.chamadas == 0
    # Recusar não deve ter efeito colateral de estado (ex.: autopilot marcando running).
    assert svc.get(oid).status != "running"


@pytest.mark.parametrize("entrada", ["analyze_folder", "heal_docs"])
def test_pendencia_recusa_entradas_de_workspace(entrada: str, tmp_path: Path) -> None:
    svc, provider, oid = _cenario(tmp_path)
    with pytest.raises(ValueError, match="aguardando aprovação humana"):
        getattr(svc, entrada)(oid)
    assert provider.chamadas == 0


def test_apos_aprovar_a_execucao_segue() -> None:
    svc, provider, oid = _cenario()
    svc.decide_approval(_estrategia(svc, oid), approved=True)
    resultado = svc.run_plan(oid)
    assert resultado["count"] >= 1
    assert provider.chamadas >= 1


def test_rejeitar_cancela_e_continua_bloqueando_mesmo_apos_resume() -> None:
    svc, provider, oid = _cenario()
    svc.decide_approval(_estrategia(svc, oid), approved=False)
    assert svc.get(oid).status == "cancelled"
    assert any(e.type == "StrategyRejected" for e in svc.timeline(oid))
    # Tentativa de burla: retomar o kill-switch não reabilita a estratégia negada.
    svc.resume(oid)
    with pytest.raises(ValueError, match="rejeitada"):
        svc.run_plan(oid)
    with pytest.raises(ValueError, match="rejeitada"):
        svc.run_card(oid, _um_card(svc, oid))
    assert provider.chamadas == 0


def test_orquestracao_sem_aprovacao_de_estrategia_nao_muda() -> None:
    provider = _ProviderContador()
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration("backend")
    assert not [a for a in svc.list_approvals(orch.id) if a.tipo == "estrategia"]
    assert svc.run_plan(orch.id)["count"] >= 1
    assert provider.chamadas >= 1


def test_api_devolve_409_com_pendencia() -> None:
    svc, provider, oid = _cenario()
    client = TestClient(create_app(svc))
    card_id = _um_card(svc, oid)
    rotas = [
        f"/v1/orchestrations/{oid}/autopilot",
        f"/v1/orchestrations/{oid}/cards/{card_id}/run",
        f"/v1/orchestrations/{oid}/run-plan",
        f"/v1/orchestrations/{oid}/run-phase",
    ]
    for rota in rotas:
        resposta = client.post(rota, json={})
        assert resposta.status_code == 409, rota
        assert "aprovação humana" in resposta.json()["detail"]
    assert provider.chamadas == 0
