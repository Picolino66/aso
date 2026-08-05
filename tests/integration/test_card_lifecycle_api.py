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
