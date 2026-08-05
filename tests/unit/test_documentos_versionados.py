"""Versionamento de documentos em ring (§4.2 do plano4.md, ADR-0021).

Cobre `control/documentos.py` isoladamente (unit puro) e, via `OrchestrationService`,
que `run_discovery`/`run_spec` de fato acrescentam versões (não sobrescrevem) e que
`decide_discovery`/`approve_spec`/`run_spec_review` atualizam a versão corrente no
lugar, sem criar uma nova.
"""

from __future__ import annotations

from pathlib import Path

from aso.control.discovery import STATUS_APROVADO as DISCOVERY_APROVADO
from aso.control.discovery import STATUS_REPROVADO as DISCOVERY_REPROVADO
from aso.control.discovery import DiscoveryReport
from aso.control.documentos import LIMITE_RING, acrescentar_versao, proxima_versao, versao_atual
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.shared.types import RiskLevel

# --------------------------------------------------------------------- control/documentos.py


def test_ring_vazio_proxima_versao_e_1() -> None:
    assert proxima_versao([]) == 1


def test_versao_atual_de_ring_vazio_devolve_default() -> None:
    resultado = versao_atual([], DiscoveryReport)
    assert resultado.status == DiscoveryReport().status
    assert resultado.versao == 1


def test_acrescentar_versao_incrementa() -> None:
    ring: list[dict[str, object]] = []
    for i in range(1, 4):
        doc = DiscoveryReport(problema=f"v{i}")
        doc.versao = proxima_versao(ring)
        ring = acrescentar_versao(ring, doc)
    assert [d["versao"] for d in ring] == [1, 2, 3]
    assert versao_atual(ring, DiscoveryReport).problema == "v3"


def test_ring_limitado_a_5_descarta_o_mais_antigo() -> None:
    ring: list[dict[str, object]] = []
    for i in range(1, 8):  # 7 versões, limite 5
        doc = DiscoveryReport(problema=f"v{i}")
        doc.versao = proxima_versao(ring)
        ring = acrescentar_versao(ring, doc)
    assert len(ring) == LIMITE_RING
    assert [d["versao"] for d in ring] == [3, 4, 5, 6, 7]  # v1/v2 descartadas
    assert versao_atual(ring, DiscoveryReport).problema == "v7"


def test_versao_continua_monotonica_apos_descarte() -> None:
    """A sexta versão não pode reciclar o número de uma versão descartada."""
    ring: list[dict[str, object]] = []
    for i in range(1, 7):
        doc = DiscoveryReport(problema=f"v{i}")
        doc.versao = proxima_versao(ring)
        ring = acrescentar_versao(ring, doc)
    assert proxima_versao(ring) == 7


# -------------------------------------------------------- via OrchestrationService (discovery)


def test_run_discovery_acrescenta_versao_nao_sobrescreve(tmp_path: Path) -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration(
        "ajustar frete",
        target_path=str(tmp_path),
        demand_brief=DemandBrief(problema="frete errado", risco=RiskLevel.HIGH),
    )
    svc.run_discovery(orch.id)
    orch = svc.run_discovery(orch.id)  # segunda rodada
    assert len(orch.discovery_reports) == 2
    assert orch.discovery_reports[0]["versao"] == 1
    assert orch.discovery_reports[1]["versao"] == 2


def test_decide_discovery_atualiza_no_lugar_sem_criar_versao(tmp_path: Path) -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration(
        "ajustar frete",
        target_path=str(tmp_path),
        demand_brief=DemandBrief(problema="frete errado", risco=RiskLevel.HIGH),
    )
    svc.run_discovery(orch.id)
    orch = svc.decide_discovery(orch.id, approved=True)
    assert len(orch.discovery_reports) == 1
    assert orch.discovery_reports[0]["status"] == DISCOVERY_APROVADO


def test_reprovar_e_rodar_de_novo_preserva_historico(tmp_path: Path) -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration(
        "ajustar frete",
        target_path=str(tmp_path),
        demand_brief=DemandBrief(problema="frete errado", risco=RiskLevel.HIGH),
    )
    svc.run_discovery(orch.id)
    orch = svc.decide_discovery(orch.id, approved=False, comentario="faltou o cache")
    assert orch.discovery_reports[0]["status"] == DISCOVERY_REPROVADO
    orch = svc.run_discovery(orch.id)  # nova versão, mesma orquestração
    assert len(orch.discovery_reports) == 2
    # A versão reprovada continua no histórico, intacta.
    assert orch.discovery_reports[0]["status"] == DISCOVERY_REPROVADO
    assert orch.discovery_reports[0]["revisao_comentarios"] == "faltou o cache"
