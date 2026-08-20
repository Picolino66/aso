"""Cancelamento de card e bloqueio por dependência pendente pela API (ADR-0018)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.models import DecisionInput
from aso.control.orchestration_service import OrchestrationService
from aso.shared.types import RiskLevel


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_cancelar_card_move_para_cancelled() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda qualquer"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]

    resposta = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/cancel", json={"reason": "não é mais necessário"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "Cancelled"

    card = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]
    assert card["status"] == "Cancelled"


def test_run_card_com_dependencia_pendente_devolve_409() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    din = DecisionInput(
        user_request="implementar recurso seguro",
        domains=["backend", "security"],
        risk_level=RiskLevel.HIGH,
        parallelizable=True,
        needs_independent_review=True,
        impacts=["security"],
    )
    # Cria direto pelo serviço (o endpoint HTTP não aceita DecisionInput customizado —
    # a triagem decide isso); só a checagem de dependência precisa ser via API aqui.
    orch = svc.create_orchestration("implementar recurso seguro", decision_input=din)
    cards = client.get(f"/v1/orchestrations/{orch.id}/cards").json()
    review_id = next(c["id"] for c in cards if c["assignee"] == "ReviewAgent")

    resposta = client.post(f"/v1/orchestrations/{orch.id}/cards/{review_id}/run")
    assert resposta.status_code == 409

    cards_depois = client.get(f"/v1/orchestrations/{orch.id}/cards").json()
    card = next(c for c in cards_depois if c["id"] == review_id)
    assert card["status"] == "Blocked"
    assert card["blocked_by"]
    # §10, ADR-0030: bloqueio por dependência cria uma tarefa vinculada automática.
    assert card["dependency_task_id"] is not None
    tarefa = next(c for c in cards_depois if c["id"] == card["dependency_task_id"])
    assert tarefa["type"] == "Task"
    assert tarefa["status"] == "Backlog"


def test_checklist_de_preparacao_via_api() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda qualquer"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]

    vazio = client.get(f"/v1/orchestrations/{oid}/cards/{card_id}/checklist")
    assert vazio.status_code == 200
    assert vazio.json() == []

    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")

    depois = client.get(f"/v1/orchestrations/{oid}/cards/{card_id}/checklist").json()
    assert len(depois) >= 5
    assert all("item" in i and "autor" in i and "at" in i for i in depois)


def test_checklist_card_inexistente_devolve_404() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda qualquer"}).json()["id"]
    resposta = client.get(f"/v1/orchestrations/{oid}/cards/card_inexistente/checklist")
    assert resposta.status_code == 404
