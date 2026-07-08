"""Testes da camada de consulta (CQRS-lite) no serviço, API e CLI."""

from __future__ import annotations

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from aso.api.app import create_app
from aso.cli.main import app as cli_app
from aso.control.orchestration_service import OrchestrationService


def _svc_with_run() -> tuple[OrchestrationService, str, str]:
    svc = OrchestrationService()
    orch = svc.create_orchestration("Implementar backend X")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)  # move o card para Testing
    return svc, orch.id, card.id


def test_service_queries() -> None:
    svc, oid, card_id = _svc_with_run()
    assert svc.count_cards_by_status(oid) == {"Testing": 1}
    assert svc.cards_by_status(oid, "Testing") == [card_id]
    assert svc.adrs_by_status(oid, "accepted") == ["ADR-0001"]
    assert svc.cards_linked_to_adr(oid, "ADR-0001") == []


def test_api_query_endpoints() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "X"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")

    assert client.get(f"/v1/orchestrations/{oid}/cards/stats").json() == {"Testing": 1}
    assert client.get(f"/v1/orchestrations/{oid}/cards/by-status/Testing").json() == [card_id]
    assert client.get(f"/v1/orchestrations/{oid}/adrs/by-status/accepted").json() == ["ADR-0001"]
    assert client.get(f"/v1/orchestrations/{oid}/adrs/ADR-0001/linked-cards").json() == []
    assert client.get("/v1/orchestrations/nope/cards/stats").status_code == 404


def test_cli_stats_command() -> None:
    from aso.cli.main import _service

    orch = _service.create_orchestration("Y")
    card = _service.get_cards(orch.id)[0]
    _service.run_card(orch.id, card.id)
    result = CliRunner().invoke(cli_app, ["stats", orch.id])
    assert result.exit_code == 0
    assert "Testing" in result.stdout
