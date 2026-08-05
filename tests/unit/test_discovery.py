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

from aso.control.discovery import DiscoveryReport, DiscoveryService, exige_aprovacao_discovery
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
