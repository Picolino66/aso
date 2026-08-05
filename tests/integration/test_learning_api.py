"""Aprendizado da esteira pela API (§24 do fluxo.md, ADR-0025)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


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
