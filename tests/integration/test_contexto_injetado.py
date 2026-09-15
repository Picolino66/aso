"""MEL-19 — contexto do ledger/spec/discovery chegando de fato ao agente (ADR-0063)."""

from __future__ import annotations

from typing import Any

from aso.agents.executor import LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.control.discovery import STATUS_APROVADO
from aso.control.models import DecisionInput
from aso.control.orchestration_service import OrchestrationService
from aso.shared.types import Phase


class _Espiao(LocalMockExecutionProvider):
    def __init__(self) -> None:
        self.tarefas: list[dict[str, Any]] = []

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        self.tarefas.append(task)
        return super().execute(agent, task)


def _chaves(tarefa: dict[str, Any]) -> list[str]:
    return [i["chave"] for i in tarefa["envelope"]["contexto"]["itens"]]


def test_card_de_f5_recebe_a_saida_do_card_de_f2() -> None:
    espiao = _Espiao()
    svc = OrchestrationService(provider=espiao)
    oid = svc.create_orchestration(
        "arquitetura e backend",
        decision_input=DecisionInput(user_request="x", domains=["architecture", "backend"]),
    ).id
    card_f2 = next(c for c in svc.get_cards(oid) if c.phase == Phase.F2)
    card_f5 = next(c for c in svc.get_cards(oid) if c.phase == Phase.F5)
    svc.run_card(oid, card_f2.id)
    svc.run_card(oid, card_f5.id)

    tarefa_f5 = espiao.tarefas[-1]
    assert "ledger:architecture" in _chaves(tarefa_f5)
    arquitetura = next(
        i for i in tarefa_f5["envelope"]["contexto"]["itens"] if i["chave"] == "ledger:architecture"
    )
    assert card_f2.id in arquitetura["conteudo"]  # a saída do F2 está sob a chave do card


def test_card_da_spec_recebe_item_de_origem_e_discovery_aprovado() -> None:
    espiao = _Espiao()
    svc = OrchestrationService(provider=espiao)
    oid = svc.create_orchestration("backend").id
    card = svc.get_cards(oid)[0]
    b = svc._bundle(oid)  # noqa: SLF001 - simula discovery aprovado e spec gerada
    b.orchestration.discovery_reports = [
        {"status": STATUS_APROVADO, "problema": "cálculo manual", "recomendacao_tecnica": "API"}
    ]
    b.orchestration.spec_documents = [
        {
            "status": "aprovado",
            "itens_de_trabalho": [
                {
                    "titulo": "Épico",
                    "itens_filhos": [
                        {"titulo": card.title, "descricao": "do item de origem", "fase": "F5"}
                    ],
                }
            ],
        }
    ]
    svc.run_card(oid, card.id)
    tarefa = espiao.tarefas[-1]
    chaves = _chaves(tarefa)
    assert {"card", "spec", "discovery"} <= set(chaves)
    itens = {i["chave"]: i["conteudo"] for i in tarefa["envelope"]["contexto"]["itens"]}
    assert "do item de origem" in itens["spec"]
    assert "cálculo manual" in itens["discovery"]


def test_dois_cards_do_mesmo_papel_nao_sobrescrevem_a_mesma_chave() -> None:
    svc = OrchestrationService()
    oid = svc.create_orchestration("backend").id
    b = svc._bundle(oid)  # noqa: SLF001
    original = svc.get_cards(oid)[0]
    segundo = original.model_copy(update={"id": "card_segundo", "title": "Outro trabalho"})
    b.board_service.add_card(segundo)
    svc.run_card(oid, original.id)
    svc.run_card(oid, segundo.id)
    engenharia = svc.get_context(oid)["payload"]["engineering"]  # type: ignore[index]
    assert {original.id, "card_segundo"} <= set(engenharia)


def test_evento_agent_executed_registra_tamanho_e_omissoes_do_contexto(monkeypatch: Any) -> None:
    monkeypatch.setenv("ASO_CONTEXTO_MAX_CHARS", "1000")
    svc = OrchestrationService()
    oid = svc.create_orchestration("backend").id
    card = svc.get_cards(oid)[0]
    svc._bundle(oid).orchestration.demand_brief = {"objetivo": "z" * 5_000}  # noqa: SLF001
    svc.run_card(oid, card.id)
    evento = next(e for e in svc.timeline(oid) if e.type == "AgentExecuted")
    assert evento.payload["contexto_chars"] > 0
    assert "demanda" in evento.payload["contexto_omitidos"]
