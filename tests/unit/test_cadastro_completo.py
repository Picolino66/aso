"""Campos novos da Tela 03 (Cadastro de demanda completo, wf §5.2) — ADR-0039."""

from __future__ import annotations

from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.shared.types import RiskLevel


def test_demand_brief_novos_campos_tem_default_seguro() -> None:
    brief = DemandBrief()
    assert brief.solicitante == ""
    assert brief.origem_da_demanda == ""
    assert brief.sistemas_afetados == []
    assert brief.apis_afetadas == []
    assert brief.banco_de_dados_afetado == []
    assert brief.infraestrutura_afetada == []
    assert brief.dependencias_conhecidas == []
    assert brief.restricoes == []
    assert brief.evidencias_esperadas == []
    assert brief.aprovacao_humana_obrigatoria is False
    assert brief.prazo is None


def test_demand_brief_novos_campos_sobrevivem_a_round_trip_json() -> None:
    brief = DemandBrief(
        solicitante="Maria",
        origem_da_demanda="ticket #123",
        sistemas_afetados=["billing"],
        apis_afetadas=["/v1/pagamentos"],
        banco_de_dados_afetado=["postgres-principal"],
        infraestrutura_afetada=["k8s-prod"],
        dependencias_conhecidas=["serviço de notificações"],
        restricoes=["não pode quebrar contrato público"],
        evidencias_esperadas=["print do relatório"],
        aprovacao_humana_obrigatoria=True,
        prazo="2026-12-01",
    )
    reidratado = DemandBrief.model_validate(brief.model_dump(mode="json"))
    assert reidratado == brief


def test_aprovacao_humana_obrigatoria_forca_plan_requires_human_approval() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration(
        "demanda de baixo risco",
        demand_brief=DemandBrief(risco=RiskLevel.LOW, aprovacao_humana_obrigatoria=True),
    )
    plano = svc.get_plan(orch.id)
    assert plano.requires_human_approval is True
    pendentes = [a for a in svc.list_approvals(orch.id) if a.status == "pending"]
    assert pendentes
    # Honesto sobre a causa real — não só o motivo (possivelmente conservador) do
    # motor de decisão, que sozinho talvez nem tivesse pedido aprovação.
    assert "aprovação humana marcada como obrigatória" in pendentes[0].reason


def test_sem_aprovacao_humana_obrigatoria_baixo_risco_nao_exige_aprovacao() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration(
        "demanda de baixo risco", demand_brief=DemandBrief(risco=RiskLevel.LOW)
    )
    plano = svc.get_plan(orch.id)
    assert plano.requires_human_approval is False


def test_orcamento_usd_na_criacao_sobrescreve_o_default() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda com orçamento", orcamento_usd=42.5)
    assert orch.orcamento_usd == 42.5


def test_sem_orcamento_usd_usa_o_default_de_ambiente() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda sem orçamento explícito")
    assert orch.orcamento_usd == svc._orcamento_padrao_usd  # noqa: SLF001
