"""(a) Série temporal de SLO persistida + tendência por janela; (c) burn-rate no Prometheus."""

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


def test_slo_evaluate_persists_and_history_survives_reload() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    client = TestClient(create_app(svc))

    e1 = client.post(f"/v1/orchestrations/{orch.id}/slo/evaluate")
    assert e1.status_code == 201
    assert e1.json()["id"].startswith("slo")

    client.post(f"/v1/orchestrations/{orch.id}/slo/evaluate")
    svc._bundles.clear()  # noqa: SLF001 — força reidratação do repositório
    hist = client.get(f"/v1/orchestrations/{orch.id}/slo-history").json()
    assert len(hist) == 2
    assert all("burn_rate" in h and "consumed_pct" in h for h in hist)
    # limite retorna as mais recentes
    assert len(client.get(f"/v1/orchestrations/{orch.id}/slo-history?limit=1").json()) == 1


def test_trend_uses_persisted_history() -> None:
    # 1ª amostra saudável (burn 0); depois falhas elevam o consumo → tendência 'rising'.
    svc = OrchestrationService(provider=AlwaysFailProvider())
    orch = svc.create_orchestration("backend")
    m = MetricsService(svc)

    svc.record_slo_evaluation(orch.id, _sample(svc, orch.id, m))  # amostra saudável (burn 0)
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)  # gera falha → consumo sobe

    report = m.slo_report(orch.id)
    assert report["error_budget"]["samples"] >= 1
    assert report["error_budget"]["trend"] == "rising"


def _sample(svc: OrchestrationService, oid: str, m: MetricsService) -> Any:
    from aso.governance.models import SloEvaluation

    eb = m.slo_report(oid)["error_budget"]
    return SloEvaluation(
        orchestration_id=oid,
        fail_rate=eb["fail_rate"],
        burn_rate=eb["burn_rate"],
        consumed_pct=eb["consumed_pct"],
        severity=eb["severity"],
    )


def test_prometheus_exposes_burn_rate_gauges() -> None:
    svc = OrchestrationService()
    svc.create_orchestration("backend")
    body = MetricsService(svc).prometheus()
    assert "aso_slo_burn_rate{" in body
    assert "aso_error_budget_consumed_pct{" in body
