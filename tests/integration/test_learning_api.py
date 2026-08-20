"""Aprendizado da esteira pela API (§24 do fluxo.md, ADR-0025; Tela 29,
wf §31, ADR-0052)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.shared.types import Phase, RiskLevel


def test_relatorio_vazio_para_orquestracao_sem_falhas() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("demanda qualquer")

    resposta = client.get(f"/v1/orchestrations/{orch.id}/learning")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total_cards"] >= 1
    assert corpo["total_falhas"] == 0
    assert all(d["falhas"] == 0 for d in corpo["desempenho_por_executor"])


def test_relatorio_reflete_falha_de_qa_registrada() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    card.executor = "claude-opus"
    svc.register_qa_check(orch.id, card.id, cenario="checkout")
    svc.fail_qa_check(orch.id, card.id, 0, resultado_obtido="quebrou")

    corpo = client.get(f"/v1/orchestrations/{orch.id}/learning").json()
    assert corpo["total_falhas"] == 1
    assert corpo["erros_recorrentes"] == {"qa": 1}
    executores = {d["executor"]: d for d in corpo["desempenho_por_executor"]}
    assert executores["claude-opus"]["falhas"] == 1


def test_learning_global_consolida_duas_orquestracoes() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch1 = svc.create_orchestration("demanda 1")
    orch2 = svc.create_orchestration("demanda 2")
    card1 = svc.get_cards(orch1.id)[0]
    card2 = svc.get_cards(orch2.id)[0]
    card1.executor = "claude-opus"
    card2.executor = "claude-opus"
    svc.register_qa_check(orch1.id, card1.id, cenario="a")
    svc.fail_qa_check(orch1.id, card1.id, 0)

    corpo = client.get("/v1/learning").json()
    assert corpo["orchestration_id"] == "todas"
    assert corpo["total_cards"] >= 2
    executores = {d["executor"]: d for d in corpo["desempenho_por_executor"]}
    assert executores["claude-opus"]["execucoes"] >= 2
    assert executores["claude-opus"]["falhas"] == 1


# ----------------------------------------- Tela 29: indicadores novos (wf §31.1)


def test_learning_relatorio_tem_falhas_por_agente_real() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("demanda com falha")
    card = svc.get_cards(orch.id)[0]
    svc.register_qa_check(orch.id, card.id, cenario="checkout")
    svc.fail_qa_check(orch.id, card.id, 0, resultado_obtido="quebrou")

    corpo = client.get(f"/v1/orchestrations/{orch.id}/learning").json()
    assert corpo["falhas_por_agente"]
    assert sum(corpo["falhas_por_agente"].values()) == corpo["total_falhas"]


def test_learning_relatorio_sem_atividade_tem_taxas_none() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("demanda vazia")
    corpo = client.get(f"/v1/orchestrations/{orch.id}/learning").json()
    assert corpo["taxa_aprovacao"] is None
    assert corpo["taxa_rollback"] is None
    assert corpo["cobertura_de_testes"] is None


def _orch_pronta(svc: OrchestrationService, tmp_path: Path, *, risco: RiskLevel) -> str:
    orch = svc.create_orchestration(
        "ajustar cálculo de frete",
        target_path=str(tmp_path),
        seed_cards=False,
        demand_brief=DemandBrief(risco=risco),
    )
    svc.run_quality_gate(orch.id, Phase.F5)
    return orch.id


def test_learning_reflete_taxa_de_rollback_real(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    client.post(f"/v1/orchestrations/{oid}/deploy/rollback", json={"reason": "bug crítico"})

    corpo = client.get(f"/v1/orchestrations/{oid}/learning").json()
    assert corpo["taxa_rollback"] == 1.0


def test_learning_reflete_taxa_de_aprovacao_real() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("demanda com aprovação")
    aprovacao = client.post(
        f"/v1/orchestrations/{orch.id}/approvals",
        json={"action": "merge", "risk": "high", "reason": "teste"},
    ).json()
    client.post(f"/v1/approvals/{aprovacao['id']}/approve")

    corpo = client.get(f"/v1/orchestrations/{orch.id}/learning").json()
    assert corpo["taxa_aprovacao"] == 1.0


def test_learning_global_filtra_por_projeto(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    projeto = client.post(
        "/v1/projects", json={"name": "Projeto X", "target_path": str(tmp_path)}
    ).json()
    svc.create_orchestration("demanda no projeto", project_id=projeto["id"])
    svc.create_orchestration("demanda fora do projeto")

    todas = client.get("/v1/learning").json()
    so_projeto = client.get(f"/v1/learning?projeto={projeto['id']}").json()
    assert so_projeto["total_cards"] < todas["total_cards"]
    assert so_projeto["total_cards"] >= 1


# --------------------------------- Tela 29: recomendações estruturadas (wf §31.3)


def test_learning_recommendations_tem_oito_categorias() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("demanda qualquer")
    resposta = client.get(f"/v1/orchestrations/{orch.id}/learning/recommendations")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 8
    desabilitadas = [r for r in corpo if not r["disponivel"]]
    assert len(desabilitadas) == 2


def test_learning_recommendations_global_aceita_filtros() -> None:
    client = TestClient(create_app(OrchestrationService()))
    resposta = client.get("/v1/learning/recommendations?projeto=inexistente")
    assert resposta.status_code == 200
    assert len(resposta.json()) == 8
