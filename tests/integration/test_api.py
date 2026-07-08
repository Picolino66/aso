"""Teste de integração da API v1 (TASK-13)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_create_and_fetch_orchestration() -> None:
    client = _client()
    resp = client.post("/v1/orchestrations", json={"user_request": "Criar módulo PDF"})
    assert resp.status_code == 201
    oid = resp.json()["id"]

    assert client.get(f"/v1/orchestrations/{oid}").status_code == 200
    assert client.get(f"/v1/orchestrations/{oid}/plan").json()["strategy"] == "single_agent"
    assert client.get(f"/v1/orchestrations/{oid}/adrs").json()  # >= 1 ADR
    assert len(client.get(f"/v1/orchestrations/{oid}/cards").json()) == 1


def test_run_card_and_gate() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "backend X"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]

    run = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")
    assert run.status_code == 200
    assert run.json()[0]["status"] == "applied"

    gate = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={})
    assert gate.json()["status"] == "PASSED"
    assert client.get(f"/v1/orchestrations/{oid}/snapshots").json()


def test_unknown_orchestration_returns_404() -> None:
    client = _client()
    assert client.get("/v1/orchestrations/nope").status_code == 404
