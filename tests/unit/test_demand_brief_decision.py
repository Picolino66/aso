"""Prova de que a ficha da demanda alimenta o motor de decisão (Incremento A).

Antes deste incremento, `MultiAgentDecisionEngine` decidia sempre sobre a mesma
constante (`domains=["backend"]`, `risk_level=LOW`) porque nada preenchia
`decision_input` na criação da orquestração — ver diagnóstico em `plano.md`. Estes
testes provam que a ficha triada agora tem efeito real sobre estratégia, equipe,
aprovação humana e prioridade dos cards — e que uma demanda sem nenhum sinal continua
produzindo exatamente o comportamento de antes (regressão coberta).
"""

from __future__ import annotations

from aso.control.models import Orchestration
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.shared.types import ExecutionStrategy, RiskLevel


def _svc() -> OrchestrationService:
    return OrchestrationService()


def _criar(svc: OrchestrationService, demanda: str) -> tuple[Orchestration, DemandBrief]:
    brief = svc.triage_demand(demanda)
    orch = svc.create_orchestration(
        demanda, decision_input=brief.to_decision_input(demanda), demand_brief=brief
    )
    return orch, brief


DEMANDA_MULTIDOMINIO = "Revisar login com token e senha, guardando os dados no banco de dados"


def test_demanda_multidominio_de_alto_risco_deixa_de_ser_single_agent() -> None:
    svc = _svc()
    orch, brief = _criar(svc, DEMANDA_MULTIDOMINIO)
    plan = svc._bundle(orch.id).plan  # noqa: SLF001 - o plano é o próprio objeto do teste
    assert brief.risco == RiskLevel.HIGH
    assert plan.strategy != ExecutionStrategy.SINGLE_AGENT
    assert any(a.agent == "ReviewAgent" for a in plan.agents)


def test_impacto_deploy_gera_aprovacao_humana_pendente_na_criacao() -> None:
    svc = _svc()
    orch, brief = _criar(svc, "Publicar a nova versão em produção via deploy")
    assert "deploy" in brief.impactos
    aprovacoes = svc._bundle(orch.id).approvals  # noqa: SLF001
    assert any(a.status == "pending" for a in aprovacoes)


def test_card_priority_reflete_o_risco_da_ficha_e_nao_e_mais_fixo_em_medium() -> None:
    svc = _svc()
    orch, brief = _criar(svc, DEMANDA_MULTIDOMINIO)
    assert brief.risco == RiskLevel.HIGH
    cards = svc.get_cards(orch.id)
    assert cards
    assert all(c.priority == RiskLevel.HIGH for c in cards)


def test_demanda_sem_nenhum_sinal_reproduz_exatamente_o_plano_de_hoje() -> None:
    """Regressão: sem sinal, `SINGLE_AGENT` + domínio `backend` + risco `LOW`.

    A asserção de `priority` foi acrescentada pela avaliação do Incremento A
    (Ponto 1, Incremento B): foi por não checar isto que a regressão
    `medium` → `low` da CLI (que não passava pela triagem) passou despercebida.
    """
    svc = _svc()
    orch, brief = _criar(svc, "Ajustar o relatório mensal de vendas totais")
    plan = svc._bundle(orch.id).plan  # noqa: SLF001
    assert brief.dominios == ["backend"]
    assert brief.risco == RiskLevel.LOW
    assert plan.strategy == ExecutionStrategy.SINGLE_AGENT
    assert not plan.requires_human_approval
    cards = svc.get_cards(orch.id)
    assert cards
    assert all(c.priority == RiskLevel.LOW for c in cards)
