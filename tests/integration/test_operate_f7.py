"""Testes F7 — observabilidade (métricas/SLOs) e feedback → backlog."""

from __future__ import annotations

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from aso.api.app import create_app
from aso.cli.main import app as cli_app
from aso.control.orchestration_service import OrchestrationService
from aso.observability.metrics import MetricsService


def _run() -> tuple[OrchestrationService, str]:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend X")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)
    svc.run_quality_gate(orch.id)
    return svc, orch.id


def test_orchestration_metrics_and_slos() -> None:
    svc, oid = _run()
    m = MetricsService(svc)
    metrics = m.orchestration_metrics(oid)
    assert metrics["cards_total"] == 1
    assert metrics["adrs_total"] >= 1
    assert metrics["snapshots_total"] == 1
    assert metrics["open_conflicts"] == 0

    report = m.slo_report(oid)
    assert report["breaches"] == []  # sem conflitos, sem bloqueios, snapshot != O0


def test_global_metrics() -> None:
    svc, oid = _run()
    g = MetricsService(svc).global_metrics()
    assert g["orchestrations_total"] == 1
    assert g["cards_by_status"].get("Testing") == 1


def test_feedback_creates_backlog_card() -> None:
    svc, oid = _run()
    before = len(svc.get_cards(oid))
    card = svc.add_feedback(oid, "Precisamos de export em PDF")
    assert card.type.value == "Improvement"
    assert card.status.value == "Backlog"
    assert len(svc.get_cards(oid)) == before + 1
    assert any(e.type == "FeedbackReceived" for e in svc.timeline(oid))


def test_api_metrics_slo_feedback() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "X"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")
    client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={})

    assert client.get("/v1/metrics").json()["orchestrations_total"] == 1
    assert client.get(f"/v1/orchestrations/{oid}/metrics").json()["cards_total"] == 1
    assert client.get(f"/v1/orchestrations/{oid}/slo").json()["breaches"] == []

    resp = client.post(f"/v1/orchestrations/{oid}/feedback", json={"text": "melhorar busca"})
    assert resp.status_code == 201
    assert resp.json()["type"] == "Improvement"


def test_cli_metrics_and_feedback() -> None:
    from aso.cli.main import _service

    orch = _service.create_orchestration("Z")
    card = _service.get_cards(orch.id)[0]
    _service.run_card(orch.id, card.id)
    runner = CliRunner()
    assert runner.invoke(cli_app, ["metrics", orch.id]).exit_code == 0
    fb = runner.invoke(cli_app, ["feedback", orch.id, "novo pedido"])
    assert fb.exit_code == 0
    assert "Card criado" in fb.stdout
