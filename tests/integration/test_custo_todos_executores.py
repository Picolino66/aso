"""MEL-41 — execuções via LLM e perguntas a agentes contam custo e orçamento (ADR-0070)."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from aso.application.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.llm_client import FakeLlmClient
from aso.execution.llm_provider import LlmExecutionProvider
from aso.shared.agent_usage import ORIGEM_TOKENS, UsoDoAgente
from aso.shared.types import RiskLevel

_PRECO = json.dumps({"modelo-api": {"entrada": 10.0, "saida": 30.0}})


def _llm(tokens_entrada: int = 100_000, tokens_saida: int = 10_000) -> LlmExecutionProvider:
    uso = UsoDoAgente(
        tokens_entrada=tokens_entrada,
        tokens_saida=tokens_saida,
        modelo="modelo-api",
        origem=ORIGEM_TOKENS,
    )
    cliente = FakeLlmClient(
        lambda s, u: json.dumps({"summary": "ok", "content": {"feito": True}}), uso=uso
    )
    return LlmExecutionProvider(cliente)


def test_execucao_via_llm_acumula_tokens_e_custo_no_card(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASO_PRECOS_MODELOS", _PRECO)
    svc = OrchestrationService(provider=_llm())
    oid = svc.create_orchestration("backend").id
    card = svc.get_cards(oid)[0]
    svc.run_card(oid, card.id)
    uso = svc.get_cards(oid)[0].uso
    assert uso["tokens_entrada"] == 100_000 and uso["tokens_saida"] == 10_000
    assert uso["custo_usd"] == pytest.approx(1.0 + 0.3)
    assert uso["execucoes_sem_custo"] == 0
    run = [r for r in svc.list_agent_runs(oid) if r.card_id == card.id][-1]
    assert run.custo_usd == pytest.approx(1.3) and run.uso_origem == "tabela"


def test_sem_preco_tokens_aparecem_e_custo_fica_indisponivel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ASO_PRECOS_MODELOS", raising=False)
    svc = OrchestrationService(provider=_llm())
    oid = svc.create_orchestration("backend").id
    card = svc.get_cards(oid)[0]
    svc.run_card(oid, card.id)
    uso = svc.get_cards(oid)[0].uso
    assert uso["tokens_entrada"] == 100_000
    assert uso["custo_usd"] == 0.0 and uso["execucoes_sem_custo"] == 1
    relatorio = svc.get_learning_report(oid)
    linha = relatorio.desempenho_por_executor[0]
    assert linha.execucoes_sem_custo == 1 and linha.proporcao_sem_custo == 1.0


def test_orcamento_pequeno_com_llm_precificado_freia_nova_execucao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASO_PRECOS_MODELOS", _PRECO)
    svc = OrchestrationService(provider=_llm())
    oid = svc.create_orchestration("backend", orcamento_usd=0.5).id
    cards = svc.get_cards(oid)
    svc.run_card(oid, cards[0].id)  # custa US$ 1,30: passa do teto
    svc.add_feedback(oid, "mais um card")
    novo = [c for c in svc.get_cards(oid) if c.id != cards[0].id][0]
    with pytest.raises(ValueError, match="Orçamento estourado"):
        svc.run_card(oid, novo.id)


def test_perguntas_a_agentes_contam_no_orcamento(tmp_path: Path) -> None:
    resposta = json.dumps(
        {"problema": "frete errado", "recomendacao_tecnica": "corrigir", "confianca": "alta"}
    )
    envelope = json.dumps(
        {
            "type": "result",
            "result": resposta,
            "usage": {"input_tokens": 1000, "output_tokens": 200},
            "total_cost_usd": 0.75,
        }
    )
    script = 'cat > /dev/null; printf %s "$1"; exit 0'
    perfil = ExecutorProfile(
        name="discoverer", kind="cli", command=shlex.join(["bash", "-c", script, "_", envelope])
    )
    svc = OrchestrationService(catalog=ExecutorCatalog([perfil]))
    oid = svc.create_orchestration(
        "ajustar frete",
        target_path=str(tmp_path),
        demand_brief=DemandBrief(problema="frete", risco=RiskLevel.LOW),
        orcamento_usd=0.5,
    ).id
    svc.run_discovery(oid, executor="discoverer")

    run = [r for r in svc.list_agent_runs(oid) if r.task_type == "discovery"][-1]
    assert run.custo_usd == pytest.approx(0.75) and run.tokens_entrada == 1000
    assert svc._gasto_usd(svc._bundle(oid)) == pytest.approx(0.75)  # noqa: SLF001
    card = svc.get_cards(oid)[0]
    with pytest.raises(ValueError, match="Orçamento estourado"):
        svc.run_card(oid, card.id)


def test_repositorio_sql_soma_so_o_custo_das_perguntas(tmp_path: Path) -> None:
    from aso.db.repository import SqlAlchemyAgentRunRepository
    from aso.observability.agent_runs import KIND_ASK, KIND_EXECUTE, AgentRun

    repo = SqlAlchemyAgentRunRepository(f"sqlite:///{tmp_path / 'runs.db'}")
    repo.salvar(AgentRun(orchestration_id="o1", kind=KIND_ASK, custo_usd=0.25))
    repo.salvar(AgentRun(orchestration_id="o1", kind=KIND_ASK, custo_usd=0.5))
    repo.salvar(AgentRun(orchestration_id="o1", kind=KIND_EXECUTE, custo_usd=9.0))
    repo.salvar(AgentRun(orchestration_id="o2", kind=KIND_ASK, custo_usd=1.0))
    assert repo.custo_de_perguntas("o1") == pytest.approx(0.75)
    assert repo.custo_de_perguntas("sem-runs") == 0.0
