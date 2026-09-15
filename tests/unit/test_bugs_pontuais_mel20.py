"""MEL-20 — bugs pontuais da revisão, cada um com teste que falhava antes da correção."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from aso.agents.executor import LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.agents.registry import _DEFAULT_AGENTS, FASE_PADRAO_POR_PAPEL
from aso.api.app import create_app
from aso.application.intake import _phase_for_agent
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.execution.llm_client import LlmError
from aso.shared.types import ColumnKey, Phase


# ------------------------------------------------------------- Bug 1: fase por papel
@pytest.mark.parametrize(
    ("papel", "fase"),
    [
        ("RequirementsAgent", Phase.F1),  # antes F4 ("ui" em "req-ui-rements")
        ("ProductStrategyAgent", Phase.F1),  # antes F5
        ("DevOpsAgent", Phase.F6),  # antes F5 (a doc diz F6)
        ("ArchitectureDesignAgent", Phase.F2),
        ("DataApiContractsAgent", Phase.F3),
        ("UxPlanningAgent", Phase.F4),
        ("BackendDevelopmentAgent", Phase.F5),
        ("ReviewAgent", Phase.F6),
        ("FinalResponseAgent", Phase.F7),
    ],
)
def test_tabela_papel_fase(papel: str, fase: Phase) -> None:
    assert _phase_for_agent(papel) == fase


def test_todos_os_16_papeis_tem_fase_declarada() -> None:
    papeis = {str(a["role"]) for a in _DEFAULT_AGENTS}
    assert len(papeis) == 16
    assert papeis == set(FASE_PADRAO_POR_PAPEL)


def test_papel_desconhecido_nao_e_adivinhado_por_substring() -> None:
    # "BuildUiAgent" casaria "ui" (F4) na heurística antiga; papel fora da tabela → F5.
    assert _phase_for_agent("BuildUiAgent") == Phase.F5


# ------------------------------------------------ Bug 2: run_plan e cards do mesmo papel
class _Contador(LocalMockExecutionProvider):
    def __init__(self) -> None:
        self.cards: list[str] = []

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        self.cards.append(str(task.get("card_id")))
        return super().execute(agent, task)


def test_run_plan_executa_dois_cards_do_mesmo_papel() -> None:
    provider = _Contador()
    svc = OrchestrationService(provider=provider)
    oid = svc.create_orchestration("backend").id
    original = svc.get_cards(oid)[0]
    segundo = original.model_copy(update={"id": "card_mesmo_papel", "title": "Outro"})
    svc._bundle(oid).board_service.add_card(segundo)  # noqa: SLF001
    resultado = svc.run_plan(oid, concurrent=False)
    assert set(resultado["executed"]) == {original.id, "card_mesmo_papel"}  # type: ignore[arg-type]
    assert sorted(provider.cards) == sorted([original.id, "card_mesmo_papel"])


def test_run_plan_respeita_dependencias_entre_cards() -> None:
    provider = _Contador()
    svc = OrchestrationService(provider=provider)
    oid = svc.create_orchestration("backend").id
    base = svc.get_cards(oid)[0]
    dependente = base.model_copy(
        update={"id": "card_dependente", "title": "Depois", "dependencies": [base.id]}
    )
    svc._bundle(oid).board_service.add_card(dependente)  # noqa: SLF001
    resultado = svc.run_plan(oid, concurrent=False)
    assert provider.cards == [base.id, "card_dependente"]
    assert resultado["waves"] == 2


def test_run_plan_nao_roda_card_com_dependencia_externa_pendente() -> None:
    provider = _Contador()
    svc = OrchestrationService(provider=provider)
    oid = svc.create_orchestration("backend").id
    b = svc._bundle(oid)  # noqa: SLF001
    base = svc.get_cards(oid)[0]
    bloqueado = base.model_copy(update={"id": "card_bloqueado", "status": ColumnKey.BLOCKED})
    b.board_service.add_card(bloqueado)
    b.board_service.get_card(base.id).dependencies = ["card_bloqueado"]  # type: ignore[union-attr]
    svc.run_plan(oid, concurrent=False)
    assert provider.cards == []


def test_run_plan_respeita_kill_switch() -> None:
    provider = _Contador()
    svc = OrchestrationService(provider=provider)
    oid = svc.create_orchestration("backend").id
    svc.cancel(oid)
    with pytest.raises(ValueError, match="cancelada"):
        svc.run_plan(oid)
    assert provider.cards == []


# ---------------------------------------------- Bug 3: título/critério derivados da demanda
def test_card_do_motor_tem_titulo_e_criterios_da_ficha() -> None:
    svc = OrchestrationService()
    brief = DemandBrief(
        objetivo="Calcular frete por CEP", criterios_de_aceite=["CEP inválido retorna 422"]
    )
    card = svc.get_cards(svc.create_orchestration("backend", demand_brief=brief).id)[0]
    assert card.title == "Calcular frete por CEP"
    assert card.acceptance_criteria == ["CEP inválido retorna 422"]
    assert "Output do agente aplicado via ContextBus" not in card.acceptance_criteria


def test_sem_ficha_o_titulo_resume_a_demanda() -> None:
    svc = OrchestrationService()
    demanda = "Implementar exportação de relatório mensal em PDF " * 4
    card = svc.get_cards(svc.create_orchestration(demanda).id)[0]
    assert len(card.title) <= 81
    assert card.title.startswith("Implementar exportação de relatório")
    assert not card.title.startswith("BackendDevelopmentAgent:")
    assert card.acceptance_criteria[0].startswith("A entrega atende à demanda:")


# --------------------------------------------- Bug 4: falha do planejamento LLM na criação
class _LlmQueFalha:
    id = "falha"

    def complete(self, *, system: str, user: str) -> str:
        raise LlmError("provedor indisponível")


def test_falha_do_planejamento_nao_gera_500_e_registra_evento() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc, llm_client=_LlmQueFalha()))  # type: ignore[arg-type]
    resposta = client.post(
        "/v1/orchestrations",
        json={"user_request": "Criar calculadora", "execution_mode": "full-pipeline"},
    )
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert "Planejamento LLM falhou" in corpo["aviso"]
    oid = corpo["id"]
    assert any(e.type == "PlanningFailed" for e in svc.timeline(oid))
    passo = client.get(f"/v1/orchestrations/{oid}/next-step").json()
    bloqueio = next(b for b in passo["blockers"] if b["code"] == "planejamento_falhou")
    assert bloqueio["action"]["path"].endswith("/plan")
