"""MEL-52 — consultas sem hidratar agregados.

Cada teste tem duas metades: o **resultado continua o mesmo** de antes (comparação explícita
com o cálculo que varria os agregados) e o **custo caiu** (repositório espião conta `load()`).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.application.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.governance.models import ContextPatch
from aso.observability.aprendizado import consolidar
from aso.observability.metrics import MetricsService
from aso.persistence.memory import InMemoryOrchestrationRepository
from aso.shared.types import PatchType, Phase


class _RepoEspiao(SqlAlchemyOrchestrationRepository):
    """Conta quantos agregados foram hidratados (`load`) e por quais ids."""

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.carregados: list[str] = []

    def load(self, orchestration_id: str) -> Any:
        self.carregados.append(orchestration_id)
        return super().load(orchestration_id)

    def zerar(self) -> None:
        self.carregados.clear()


@pytest.fixture
def repo(tmp_path: Path) -> _RepoEspiao:
    return _RepoEspiao(f"sqlite:///{tmp_path / 'aso.db'}")


def _svc(repo: _RepoEspiao) -> OrchestrationService:
    return OrchestrationService(repository=repo)


def _com_aprovacoes(svc: OrchestrationService, quantas: int) -> list[str]:
    ids: list[str] = []
    for i in range(quantas):
        orch = svc.create_orchestration(f"demanda {i}")
        svc.request_approval(orch.id, f"decidir {i}")
        ids.append(orch.id)
    return ids


# ------------------------------------------------------- aprovações (critérios 1 e 2)


def test_decidir_aprovacao_hidrata_no_maximo_uma_orquestracao(repo: _RepoEspiao) -> None:
    svc = _svc(repo)
    ids = _com_aprovacoes(svc, 4)
    alvo = svc.list_approvals(ids[-1])[0]
    svc._bundles.clear()  # noqa: SLF001 - sem cache: cada leitura precisa ir ao repositório
    repo.zerar()

    decidida = svc.decide_approval(alvo.id, approved=True)

    assert decidida.status == "approved"
    assert repo.carregados == [ids[-1]]  # antes: as 4 orquestrações do sistema


def test_aprovacao_inexistente_nao_hidrata_nada(repo: _RepoEspiao) -> None:
    svc = _svc(repo)
    _com_aprovacoes(svc, 3)
    svc._bundles.clear()  # noqa: SLF001
    repo.zerar()

    assert svc.get_approval("approval_fantasma") is None
    assert repo.carregados == []


def test_listagem_global_de_aprovacoes_nao_hidrata_e_da_o_mesmo_resultado(
    repo: _RepoEspiao,
) -> None:
    svc = _svc(repo)
    ids = _com_aprovacoes(svc, 3)
    svc.decide_approval(svc.list_approvals(ids[0])[0].id, approved=True)
    # Cálculo antigo: varrer todos os agregados e juntar as aprovações.
    esperado = sorted(
        (a.id, a.orchestration_id, a.status)
        for oid in repo.list_ids()
        for a in svc.list_approvals(oid)
    )
    svc._bundles.clear()  # noqa: SLF001
    repo.zerar()

    obtido = svc.list_all_approvals()

    assert sorted((a.id, a.orchestration_id, a.status) for a in obtido) == esperado
    assert repo.carregados == []
    # e o filtro vai na consulta, não em memória
    pendentes = svc.list_all_approvals(status="pending")
    assert {a.orchestration_id for a in pendentes} == {ids[1], ids[2]}
    assert (
        svc.list_all_approvals(status="pending", orchestration_ids={ids[1]})[0].orchestration_id
        == ids[1]
    )
    assert svc.list_all_approvals(orchestration_ids=set()) == []
    assert repo.carregados == []


def test_rota_de_aprovacoes_filtra_por_projeto_sem_hidratar(repo: _RepoEspiao) -> None:
    svc = _svc(repo)
    client = TestClient(create_app(svc))
    ids = _com_aprovacoes(svc, 2)
    svc._bundles.clear()  # noqa: SLF001
    repo.zerar()

    corpo = client.get("/v1/approvals", params={"status": "pending"}).json()

    assert {a["orchestration_id"] for a in corpo} == set(ids)
    assert repo.carregados == []


def test_header_e_dashboard_usam_a_consulta_de_pendentes(repo: _RepoEspiao) -> None:
    svc = _svc(repo)
    ids = _com_aprovacoes(svc, 2)
    svc.decide_approval(svc.list_approvals(ids[0])[0].id, approved=False)
    svc._bundles.clear()  # noqa: SLF001

    assert svc.header_summary()["aprovacoes_pendentes"] == 1
    painel = svc.dashboard_summary()
    assert painel["aprovacoes_por_tipo"] == {"manual": 1}


# ------------------------------------------------------- métricas de execução


def test_metricas_de_execucao_saem_de_agent_runs_e_de_contagem_de_eventos(
    repo: _RepoEspiao,
) -> None:
    svc = _svc(repo)
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)
    svc.request_approval(orch.id, "segura aqui")

    metricas = MetricsService(svc).execution_metrics(orch.id)

    # mesmo resultado do cálculo antigo (contagem sobre a timeline inteira)
    eventos = svc.timeline(orch.id)
    executados = [e for e in eventos if e.type == "AgentExecuted"]
    duracoes = [float(e.payload.get("ms", 0)) for e in executados]
    assert metricas["agent_executions"] == len(executados) > 0
    assert metricas["avg_ms"] == pytest.approx(round(sum(duracoes) / len(duracoes), 1), rel=0.2)
    assert metricas["retries"] == len([e for e in eventos if e.type == "AgentRetry"])
    assert metricas["failures"] == len([e for e in eventos if e.type == "AgentFailed"])
    assert metricas["origem"] == "agent_runs"

    agregados = svc.execution_aggregates(orch.id)
    assert agregados["execucoes"] == float(len(executados))
    contagens = svc.count_events_by_type(orch.id, ("AgentExecuted", "AgentRetry", "Inexistente"))
    assert contagens["AgentExecuted"] == len(executados)
    assert contagens["Inexistente"] == 0  # tipo sem linha volta zero, não falta a chave


def test_metricas_caem_para_eventos_quando_nao_ha_run_registrado(repo: _RepoEspiao) -> None:
    """Banco anterior à ADR-0065 (ou runs expurgados): relatar zero execuções seria mentira."""
    svc = _svc(repo)
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)
    executados = len([e for e in svc.timeline(orch.id) if e.type == "AgentExecuted"])

    sem_runs = _svc(repo)  # instância nova: repositório de runs em memória, vazio
    metricas = MetricsService(sem_runs).execution_metrics(orch.id)

    assert metricas["origem"] == "eventos"
    assert metricas["agent_executions"] == executados > 0
    assert metricas["avg_ms"] > 0


# ------------------------------------------------------- aprendizado global (critério 3)


def _patch(oid: str) -> ContextPatch:
    return ContextPatch(
        orchestration_id=oid,
        agent="BackendDevelopmentAgent",
        phase=Phase.F5,
        patch_type=PatchType.UPDATE,
        target_path="engineering.notes",
        content="x",
    )


def test_aprendizado_global_usa_consultas_e_bate_com_a_soma_por_orquestracao(
    repo: _RepoEspiao,
) -> None:
    svc = _svc(repo)
    ids = []
    for i in range(3):
        orch = svc.create_orchestration(f"demanda {i}")
        card = svc.get_cards(orch.id)[0]
        svc.run_card(orch.id, card.id)
        svc.request_approval(orch.id, "conferir")
        svc.decide_approval(svc.list_approvals(orch.id)[0].id, approved=True)
        ids.append(orch.id)

    # Cálculo de referência: as MESMAS contas, mas a partir dos agregados hidratados.
    cards: list[Any] = []
    pulls: list[Any] = []
    intervencoes = 0
    extras: list[dict[str, Any]] = []
    for oid in ids:
        b = svc._bundle(oid)  # noqa: SLF001
        c, p, i = svc._insights._coletar_aprendizado(b)  # noqa: SLF001
        cards.extend(c)
        pulls.extend(p)
        intervencoes += i
        extras.append(svc._insights._coletar_indicadores_extra(b))  # noqa: SLF001
    tempo_por_etapa: dict[str, list[float]] = {}
    for extra in extras:
        for etapa, valores in extra["tempo_por_etapa_ms"].items():
            tempo_por_etapa.setdefault(etapa, []).extend(valores)
    esperado = consolidar(
        "todas",
        cards,
        pulls,
        intervencoes_humanas=intervencoes,
        aprovados=sum(e["aprovados"] for e in extras),
        decisoes_de_aprovacao=sum(e["decisoes_de_aprovacao"] for e in extras),
        rollbacks=sum(e["rollbacks"] for e in extras),
        deploys=sum(e["deploys"] for e in extras),
        sucesso_primeiro_ciclo=sum(e["sucesso_primeiro_ciclo"] for e in extras),
        total_orchestrations=len(ids),
        soma_tentativas=sum(e["soma_tentativas"] for e in extras),
        cards_com_tentativa=sum(e["cards_com_tentativa"] for e in extras),
        tempo_por_etapa_ms=tempo_por_etapa,
    )

    svc._bundles.clear()  # noqa: SLF001
    repo.zerar()
    obtido = svc.get_learning_report_global()

    assert dataclasses.asdict(obtido) == dataclasses.asdict(esperado)
    assert repo.carregados == []  # antes: um `load` por orquestração do recorte


def test_amostras_de_aprendizado_batem_entre_os_dois_adapters(tmp_path: Path) -> None:
    """Contrato único: o adapter em memória tem de devolver a mesma amostra que o SQL."""
    memoria = InMemoryOrchestrationRepository()
    sql = SqlAlchemyOrchestrationRepository(f"sqlite:///{tmp_path / 'aso.db'}")
    resultados = []
    for repositorio in (memoria, sql):
        svc = OrchestrationService(repository=repositorio)
        orch = svc.create_orchestration("comparar adapters")
        card = svc.get_cards(orch.id)[0]
        svc.run_card(orch.id, card.id)
        svc.request_approval(orch.id, "conferir")
        amostra = repositorio.amostras_de_aprendizado([orch.id])[0]
        resultados.append(
            {
                "cards": [{k: v for k, v in c.items() if k != "id"} for c in amostra["cards"]],
                "pulls": amostra["pulls"],
                "approvals": amostra["approvals"],
                "deploy_runs": amostra["deploy_runs"],
                "tempos": len(amostra["tempo_ms_por_card"]),
            }
        )
    assert resultados[0] == resultados[1]
    assert memoria.amostras_de_aprendizado([]) == []
    assert sql.amostras_de_aprendizado(["fantasma"])[0]["cards"] == []


def test_aprovacao_por_id_bate_entre_os_dois_adapters(tmp_path: Path) -> None:
    memoria = InMemoryOrchestrationRepository()
    sql = SqlAlchemyOrchestrationRepository(f"sqlite:///{tmp_path / 'aso2.db'}")
    for repositorio in (memoria, sql):
        svc = OrchestrationService(repository=repositorio)
        oid = svc.create_orchestration("x").id
        aprovacao = svc.request_approval(oid, "decidir")
        assert repositorio.orchestration_of_approval(aprovacao.id) == oid
        assert repositorio.orchestration_of_approval("approval_fantasma") is None
        assert [a.id for a in repositorio.approvals()] == [aprovacao.id]
        assert repositorio.approvals(status="approved") == []
