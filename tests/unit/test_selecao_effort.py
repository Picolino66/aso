"""Escolha automática de esforço (§9 do fluxo.md) — ADR-0022.

`sugerir_effort`/`resolver_topo` são funções puras: dada a mesma complexidade e o
mesmo risco, a sugestão é sempre a mesma — tabela, não palpite de agente.
"""

from __future__ import annotations

import pytest

from aso.control.orchestration_service import OrchestrationService
from aso.control.selecao import EFFORT_TOPO, resolver_topo, sugerir_effort
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.shared.types import Phase, RiskLevel

_MATRIZ: list[tuple[str, RiskLevel, str]] = [
    ("simples", RiskLevel.LOW, "low"),
    ("simples", RiskLevel.MEDIUM, "low"),
    ("simples", RiskLevel.HIGH, "medium"),
    ("simples", RiskLevel.CRITICAL, "medium"),
    ("intermediaria", RiskLevel.LOW, "medium"),
    ("intermediaria", RiskLevel.MEDIUM, "medium"),
    ("intermediaria", RiskLevel.HIGH, "high"),
    ("intermediaria", RiskLevel.CRITICAL, "high"),
    ("complexa", RiskLevel.LOW, "high"),
    ("complexa", RiskLevel.MEDIUM, "high"),
    ("complexa", RiskLevel.HIGH, "high"),
    ("complexa", RiskLevel.CRITICAL, "high"),
    ("estrategica", RiskLevel.LOW, "high"),
    ("estrategica", RiskLevel.MEDIUM, "high"),
    ("estrategica", RiskLevel.HIGH, EFFORT_TOPO),
    ("estrategica", RiskLevel.CRITICAL, EFFORT_TOPO),
]


@pytest.mark.parametrize(("complexidade", "risco", "esperado"), _MATRIZ)
def test_matriz_completa_do_9(complexidade: str, risco: RiskLevel, esperado: str) -> None:
    assert sugerir_effort(complexidade, risco) == esperado


def test_complexidade_desconhecida_nunca_lanca() -> None:
    assert sugerir_effort("nunca-visto", RiskLevel.LOW) in {"low", "medium", "high"}
    assert sugerir_effort("nunca-visto", RiskLevel.CRITICAL) in {"low", "medium", "high"}


def test_resolver_topo_sem_sentinela_devolve_a_propria_sugestao() -> None:
    assert resolver_topo("medium", ["low", "medium", "high"]) == "medium"


def test_resolver_topo_com_perfil_sem_degrau_acima_de_high_fica_em_high() -> None:
    """`estrategica` + risco alto num perfil comum (só low/medium/high) não estoura:
    o topo suportado é "high", igual ao vocabulário padrão."""
    assert resolver_topo(EFFORT_TOPO, ["low", "medium", "high"]) == "high"


def test_resolver_topo_sem_perfil_cai_em_high() -> None:
    assert resolver_topo(EFFORT_TOPO, []) == "high"


def test_resolver_topo_com_perfil_com_degrau_acima_de_high() -> None:
    """Perfil Codex gerenciado com um degrau extra: o topo é o último da lista
    descoberta (menor para o maior)."""
    assert resolver_topo(EFFORT_TOPO, ["low", "medium", "high", "xhigh"]) == "xhigh"


# --------------------------------------------------------- ordem de precedência


def _catalogo() -> ExecutorCatalog:
    return ExecutorCatalog([ExecutorProfile(name="barato", kind="mock", effort="low")])


def _brief_intermediaria_risco_baixo() -> DemandBrief:
    # sugerir_effort("intermediaria", LOW) == "medium" — distinto do "low" do
    # perfil "barato", então dá para provar que a sugestão realmente age.
    return DemandBrief(complexidade="intermediaria", risco=RiskLevel.LOW)


def test_chamada_explicita_vence_a_sugestao_automatica() -> None:
    svc = OrchestrationService(catalog=_catalogo())
    orch = svc.create_orchestration("backend", demand_brief=_brief_intermediaria_risco_baixo())
    b = svc._bundle(orch.id)  # noqa: SLF001
    assert svc._effective_effort(b, "barato", "explicito", phase=Phase.F5) == "explicito"  # noqa: SLF001


def test_etapa_configurada_vence_a_sugestao_automatica() -> None:
    svc = OrchestrationService(catalog=_catalogo())
    orch = svc.create_orchestration("backend", demand_brief=_brief_intermediaria_risco_baixo())
    svc.set_agent_assignment(orch.id, "F5", executor="barato", effort="fixo-da-etapa")
    b = svc._bundle(orch.id)  # noqa: SLF001
    assert svc._effective_effort(b, "barato", None, phase=Phase.F5) == "fixo-da-etapa"  # noqa: SLF001


def test_padrao_da_orquestracao_vence_a_sugestao_automatica() -> None:
    svc = OrchestrationService(catalog=_catalogo())
    orch = svc.create_orchestration(
        "backend", effort="padrao-da-orq", demand_brief=_brief_intermediaria_risco_baixo()
    )
    b = svc._bundle(orch.id)  # noqa: SLF001
    assert svc._effective_effort(b, "barato", None, phase=Phase.F5) == "padrao-da-orq"  # noqa: SLF001


def test_sugestao_automatica_preenche_o_vazio_abaixo_do_perfil() -> None:
    svc = OrchestrationService(catalog=_catalogo())
    orch = svc.create_orchestration("backend", demand_brief=_brief_intermediaria_risco_baixo())
    b = svc._bundle(orch.id)  # noqa: SLF001
    assert svc._effective_effort(b, "barato", None, phase=Phase.F5) == "medium"  # noqa: SLF001


def test_sem_ficha_a_sugestao_nao_atua_e_cai_no_perfil() -> None:
    """Orquestração que nunca triou (`demand_brief` vazio) não muda de
    comportamento — mesma garantia de não-regressão do discovery/spec."""
    svc = OrchestrationService(catalog=_catalogo())
    orch = svc.create_orchestration("backend")
    b = svc._bundle(orch.id)  # noqa: SLF001
    assert svc._effective_effort(b, "barato", None, phase=Phase.F5) == "low"  # noqa: SLF001


def test_aso_effort_automatico_desligado_restaura_comportamento_anterior() -> None:
    svc = OrchestrationService(catalog=_catalogo(), effort_automatico=False)
    orch = svc.create_orchestration("backend", demand_brief=_brief_intermediaria_risco_baixo())
    b = svc._bundle(orch.id)  # noqa: SLF001
    assert svc._effective_effort(b, "barato", None, phase=Phase.F5) == "low"  # noqa: SLF001


def test_sugestao_automatica_registra_evento_auditavel() -> None:
    svc = OrchestrationService(catalog=_catalogo())
    orch = svc.create_orchestration("backend", demand_brief=_brief_intermediaria_risco_baixo())
    b = svc._bundle(orch.id)  # noqa: SLF001
    svc._effective_effort(b, "barato", None, phase=Phase.F5)  # noqa: SLF001
    eventos = [e for e in b.event_log.all() if e.type == "EffortSugerido"]
    assert eventos and eventos[-1].payload["effort"] == "medium"
