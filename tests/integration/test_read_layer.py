"""Testes das leituras adicionais: filtros, paginação, busca e OpenAPI servido."""

from __future__ import annotations

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from aso.api.app import create_app
from aso.cli.main import app as cli_app
from aso.control.orchestration_service import OrchestrationService


def _client_with_run() -> tuple[TestClient, str]:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "X"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")
    client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={})
    return client, oid


def test_card_filters() -> None:
    client, oid = _client_with_run()
    all_cards = client.get(f"/v1/orchestrations/{oid}/cards").json()
    testing = client.get(f"/v1/orchestrations/{oid}/cards?status=Testing").json()
    assert len(all_cards) == 1
    assert len(testing) == 1
    assert client.get(f"/v1/orchestrations/{oid}/cards?status=Done").json() == []
    assert len(client.get(f"/v1/orchestrations/{oid}/cards?type=Task").json()) == 1


def test_timeline_pagination() -> None:
    client, oid = _client_with_run()
    page = client.get(f"/v1/orchestrations/{oid}/timeline?page=1&page_size=2").json()
    assert set(page) == {"items", "total", "page", "page_size"}
    assert len(page["items"]) == 2
    assert page["total"] >= 4


def test_adr_search() -> None:
    client, oid = _client_with_run()
    assert len(client.get(f"/v1/orchestrations/{oid}/adrs?status=accepted").json()) == 1
    assert client.get(f"/v1/orchestrations/{oid}/adrs?q=estrat%C3%A9gia").json()
    assert client.get(f"/v1/orchestrations/{oid}/adrs?q=inexistente_xyz").json() == []


def test_openapi_and_root_served() -> None:
    client = TestClient(create_app(OrchestrationService()))
    root = client.get("/").json()
    assert root["openapi"] == "/openapi.json"
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "ASO Runtime API"
    assert "/v1/orchestrations" in spec["paths"]


def test_cli_cards_and_adrs() -> None:
    from aso.cli.main import _service

    orch = _service.create_orchestration("Z")
    card = _service.get_cards(orch.id)[0]
    _service.run_card(orch.id, card.id)
    runner = CliRunner()
    cards_out = runner.invoke(cli_app, ["cards", orch.id, "--status", "Testing"])
    assert cards_out.exit_code == 0
    assert "Testing" in cards_out.stdout
    adrs_out = runner.invoke(cli_app, ["adrs", orch.id])
    assert adrs_out.exit_code == 0
    assert "ADR-0001" in adrs_out.stdout
