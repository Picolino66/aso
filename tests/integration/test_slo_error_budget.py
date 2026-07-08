"""(b) MVP-5 F7: error budget + burn-rate + alertas por severidade no /slo."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from aso.agents.models import AgentOutput, AgentSpec
from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.observability.metrics import MetricsService


class AlwaysFailProvider:
    id = "fail"

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        raise RuntimeError("sempre falha")


def test_slo_error_budget_healthy() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend saudável")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)
    svc.run_quality_gate(orch.id)  # gera snapshot (SLO de snapshot ok)

    report = MetricsService(svc).slo_report(orch.id)
    eb = report["error_budget"]
    assert eb["sli"] == "taxa_de_falhas_de_execucao"
    assert eb["fail_rate"] == 0.0
    assert eb["severity"] == "ok"
    assert report["breaches"] == []
    assert report["alerts"] == []


def test_slo_error_budget_breached_and_burn_rate() -> None:
    svc = OrchestrationService(provider=AlwaysFailProvider())
    orch = svc.create_orchestration("backend com falhas")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)  # execução falha → consome orçamento de erro

    report = MetricsService(svc).slo_report(orch.id)
    eb = report["error_budget"]
    assert eb["executions"] >= 1
    assert eb["failures"] >= 1
    assert eb["fail_rate"] > 0
    assert eb["burn_rate"] > 1.0  # taxa acima do orçamento
    assert eb["severity"] == "critical"
    assert eb["sli"] in report["breaches"]
    # alerta de severidade alta para o orçamento estourado
    assert any(a["slo"] == eb["sli"] and a["severity"] == "high" for a in report["alerts"])


def test_slo_endpoint_exposes_error_budget() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    client = TestClient(create_app(svc))
    body = client.get(f"/v1/orchestrations/{orch.id}/slo").json()
    assert "error_budget" in body and "alerts" in body
    assert body["error_budget"]["budget"] > 0
