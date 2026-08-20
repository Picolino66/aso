"""DiscoveryService — relatório de discovery com fallback determinístico (§3/§4).

A regra que estes testes protegem: **discovery nunca impede a esteira de seguir**.
Toda falha do agente (executor sumido do catálogo, JSON inválido, exit != 0, timeout,
tipo que não produz texto) tem que virar o relatório heurístico + motivo registrado,
nunca exceção. E `exige_aprovacao_discovery` decide corretamente entre aprovação
automática e humana (§4).
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from aso.control.discovery import (
    DiscoveryReport,
    DiscoveryService,
    avaliar_criterios_aprovacao,
    exige_aprovacao_discovery,
)
from aso.control.models import AgentAssignment
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.workspace import WorkspaceReport
from aso.shared.types import RiskLevel


def _cli(saida: str, *, exit_code: int = 0) -> ExecutorCatalog:
    """Catálogo com um 'agente de discovery' que apenas cospe `saida` e sai com `exit_code`."""
    script = f'cat > /dev/null; printf %s "$1"; exit {exit_code}'
    comando = shlex.join(["bash", "-c", script, "_", saida])
    return ExecutorCatalog([ExecutorProfile(name="discoverer", kind="cli", command=comando)])


def _ws(**kwargs: object) -> WorkspaceReport:
    base: dict[str, object] = {
        "path": "/tmp/projeto",
        "is_git": True,
        "is_empty": False,
        "has_aso_docs": False,
        "missing": [],
        "detected_modules": ["api", "worker"],
    }
    base.update(kwargs)
    return WorkspaceReport(**base)  # type: ignore[arg-type]


def _investigar(service: DiscoveryService, assignment: AgentAssignment | None) -> object:
    return service.investigar(
        assignment,
        user_request="Ajustar cálculo de frete",
        demand_brief=DemandBrief(problema="frete errado", modulos_afetados=["checkout"]),
        workspace_report=_ws(),
    )


# --------------------------------------------------------------- caminho feliz (agente)


def test_resposta_valida_do_agente_e_aceita_com_origem_do_executor() -> None:
    bruto = (
        '{"situacao_atual": "monólito Django", "problema": "frete calculado errado", '
        '"componentes_afetados": ["checkout"], "recomendacao_tecnica": "corrigir a fórmula", '
        '"confianca": "alta"}'
    )
    relatorio = _investigar(DiscoveryService(_cli(bruto)), AgentAssignment(executor="discoverer"))
    assert relatorio.situacao_atual == "monólito Django"
    assert relatorio.componentes_afetados == ["checkout"]
    assert relatorio.confianca == "alta"
    assert relatorio.origem == "discoverer"
    assert relatorio.fallback_reason == ""


def test_confianca_fora_do_vocabulario_cai_para_media() -> None:
    bruto = '{"problema": "x", "confianca": "altissima"}'
    relatorio = _investigar(DiscoveryService(_cli(bruto)), AgentAssignment(executor="discoverer"))
    assert relatorio.confianca == "media"


def test_resposta_sem_nenhum_campo_util_cai_no_fallback() -> None:
    bruto = '{"confianca": "alta"}'  # só confiança, sem nenhum conteúdo real
    relatorio = _investigar(DiscoveryService(_cli(bruto)), AgentAssignment(executor="discoverer"))
    assert relatorio.origem == "heuristica"
    assert relatorio.fallback_reason == "resposta do agente sem campos utilizáveis"


# --------------------------------------------------------------------- caminho de falha


def test_sem_assignment_usa_heuristica_direto() -> None:
    relatorio = _investigar(DiscoveryService(_cli("não deveria rodar")), None)
    assert relatorio.origem == "heuristica"
    assert relatorio.confianca == "baixa"


def test_sem_catalogo_usa_heuristica_direto() -> None:
    relatorio = _investigar(DiscoveryService(None), AgentAssignment(executor="discoverer"))
    assert relatorio.origem == "heuristica"


def test_executor_fora_do_catalogo_cai_no_fallback_com_motivo() -> None:
    relatorio = _investigar(
        DiscoveryService(ExecutorCatalog([])), AgentAssignment(executor="fantasma")
    )
    assert relatorio.origem == "heuristica"
    assert "KeyError" in relatorio.fallback_reason


def test_json_invalido_cai_no_fallback_com_motivo() -> None:
    relatorio = _investigar(
        DiscoveryService(_cli("isto não é json")), AgentAssignment(executor="discoverer")
    )
    assert relatorio.origem == "heuristica"
    assert relatorio.fallback_reason != ""


def test_exit_diferente_de_zero_cai_no_fallback() -> None:
    relatorio = _investigar(
        DiscoveryService(_cli('{"problema": "x"}', exit_code=1)),
        AgentAssignment(executor="discoverer"),
    )
    assert relatorio.origem == "heuristica"


def test_executor_sem_capacidade_de_texto_cai_no_fallback() -> None:
    catalogo = ExecutorCatalog([ExecutorProfile(name="mockador", kind="mock")])
    relatorio = _investigar(DiscoveryService(catalogo), AgentAssignment(executor="mockador"))
    assert relatorio.origem == "heuristica"
    assert "ValueError" in relatorio.fallback_reason


# ------------------------------------------------------------------------- heurística


def test_heuristica_reaproveita_ficha_e_workspace_ja_conhecidos() -> None:
    service = DiscoveryService(None)
    relatorio = service.investigar(
        None,
        user_request="texto original da demanda",
        demand_brief=DemandBrief(problema="X quebrado", modulos_afetados=["a", "b"], riscos=["r1"]),
        workspace_report=_ws(detected_modules=["a", "b"], is_git=True),
    )
    assert relatorio.problema == "X quebrado"
    assert relatorio.componentes_afetados == ["a", "b"]
    assert relatorio.riscos == ["r1"]
    assert relatorio.confianca == "baixa"
    assert "a, b" in relatorio.situacao_atual


def test_heuristica_usa_user_request_quando_ficha_nao_tem_problema() -> None:
    service = DiscoveryService(None)
    relatorio = service.investigar(
        None,
        user_request="texto original da demanda",
        demand_brief=DemandBrief(),
        workspace_report=_ws(),
    )
    assert relatorio.problema == "texto original da demanda"


# ------------------------------------------------------------ comentários de reprovação


def test_comentarios_anteriores_entram_no_pedido_ao_agente(tmp_path: Path) -> None:
    """O agente CLI recebe a task inteira (system+content) via stdin — grava o que
    recebeu num arquivo para provar que o comentário da reprovação chegou até ele."""
    destino = tmp_path / "recebido.json"
    comando = ["bash", "-c", f'cat > "{destino}"; printf %s \'{{"problema": "ajustado"}}\'']
    perfil = ExecutorProfile(name="discoverer", kind="cli", command=shlex.join(comando))
    catalogo = ExecutorCatalog([perfil])
    service = DiscoveryService(catalogo)
    service.investigar(
        AgentAssignment(executor="discoverer"),
        user_request="demanda",
        demand_brief=DemandBrief(),
        workspace_report=_ws(),
        comentarios_anteriores="faltou considerar o cache",
    )
    recebido = json.loads(destino.read_text())
    assert "faltou considerar o cache" in recebido["content"]["request"]


# ---------------------------------------------------------- exige_aprovacao_discovery


def test_exige_aprovacao_discovery_matriz() -> None:
    baixo = DemandBrief(risco=RiskLevel.LOW, impactos=[])
    alto = DemandBrief(risco=RiskLevel.HIGH, impactos=[])
    critico = DemandBrief(risco=RiskLevel.CRITICAL, impactos=[])
    arquitetura = DemandBrief(risco=RiskLevel.LOW, impactos=["architecture"])
    seguranca = DemandBrief(risco=RiskLevel.LOW, impactos=["security"])
    contract = DemandBrief(risco=RiskLevel.LOW, impactos=["contract"])

    confianca_alta = DiscoveryReport(confianca="alta")
    confianca_baixa = DiscoveryReport(confianca="baixa")

    assert exige_aprovacao_discovery(confianca_alta, baixo) is False
    assert exige_aprovacao_discovery(confianca_alta, alto) is True
    assert exige_aprovacao_discovery(confianca_alta, critico) is True
    assert exige_aprovacao_discovery(confianca_alta, arquitetura) is True
    assert exige_aprovacao_discovery(confianca_alta, seguranca) is True
    assert exige_aprovacao_discovery(confianca_alta, contract) is True
    assert exige_aprovacao_discovery(confianca_baixa, baixo) is True  # confiança baixa já basta


# --------------------------------------------------- painel de execução (Tela 06, ADR-0045)


def test_investigar_com_agente_registra_timing_e_log_reais() -> None:
    bruto = '{"problema": "x", "confianca": "alta"}'
    relatorio = _investigar(DiscoveryService(_cli(bruto)), AgentAssignment(executor="discoverer"))
    assert relatorio.started_at is not None
    assert relatorio.finished_at is not None
    assert relatorio.duration_ms is not None
    assert relatorio.duration_ms >= 0
    assert len(relatorio.log) == 2
    assert "discoverer" in relatorio.log[0]
    assert "Concluído" in relatorio.log[1]


def test_investigar_com_falha_do_agente_registra_log_de_falha() -> None:
    relatorio = _investigar(
        DiscoveryService(ExecutorCatalog([])), AgentAssignment(executor="fantasma")
    )
    assert relatorio.started_at is not None
    assert relatorio.finished_at is not None
    assert any("Falha" in linha for linha in relatorio.log)


def test_investigar_sem_assignment_nao_gera_log() -> None:
    relatorio = _investigar(DiscoveryService(_cli("não deveria rodar")), None)
    assert relatorio.started_at is None
    assert relatorio.log == []


# --------------------------------------------- checklist de aprovação (Tela 07, ADR-0045)


def test_avaliar_criterios_aprovacao_tem_os_sete_rotulos_do_wireframe() -> None:
    brief = DemandBrief(risco=RiskLevel.LOW, impactos=[])
    report = DiscoveryReport(confianca="alta")
    resultado = avaliar_criterios_aprovacao(report, brief)
    nomes = [c["nome"] for c in resultado["criterios"]]
    assert nomes == [
        "Baixo risco",
        "Escopo claro",
        "Sem mudança relevante de arquitetura",
        "Sem risco de perda de dados",
        "Sem impacto financeiro significativo",
        "Padrões já aprovados",
        "Alta confiança do agente",
    ]
    assert resultado["aprovacao_automatica"] is True
    assert resultado["motivos_escalada"] == []


def test_avaliar_criterios_aprovacao_so_tres_sao_verificados() -> None:
    brief = DemandBrief(risco=RiskLevel.LOW, impactos=[])
    report = DiscoveryReport(confianca="alta")
    resultado = avaliar_criterios_aprovacao(report, brief)
    verificados = {c["nome"] for c in resultado["criterios"] if c["verificado"]}
    assert verificados == {
        "Baixo risco",
        "Sem mudança relevante de arquitetura",
        "Sem risco de perda de dados",
        "Alta confiança do agente",
    }
    nao_verificados = {
        c["nome"]: c["atendido"] for c in resultado["criterios"] if not c["verificado"]
    }
    assert set(nao_verificados.values()) == {None}


def test_avaliar_criterios_aprovacao_motivos_reais_por_risco_alto() -> None:
    brief = DemandBrief(risco=RiskLevel.CRITICAL, impactos=[])
    report = DiscoveryReport(confianca="alta")
    resultado = avaliar_criterios_aprovacao(report, brief)
    assert resultado["aprovacao_automatica"] is False
    assert any("Risco da demanda: critical" in m for m in resultado["motivos_escalada"])


def test_avaliar_criterios_aprovacao_motivos_para_impacto_sem_linha_dedicada() -> None:
    """'security'/'contract'/'deploy' não têm linha própria entre os 7 rótulos do
    wireframe, mas continuam contribuindo para a escalada e aparecem em motivos."""
    brief = DemandBrief(risco=RiskLevel.LOW, impactos=["security", "contract"])
    report = DiscoveryReport(confianca="alta")
    resultado = avaliar_criterios_aprovacao(report, brief)
    assert resultado["aprovacao_automatica"] is False
    assert "Impacto sensível: contract." in resultado["motivos_escalada"]
    assert "Impacto sensível: security." in resultado["motivos_escalada"]
