"""(c) Métricas de execução: duração, retries, falhas, waiting-human + Prometheus."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from aso.agents.executor import LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.observability.metrics import MetricsService


class FlakyProvider:
    id = "flaky"

    def __init__(self) -> None:
        self.calls = 0
        self._mock = LocalMockExecutionProvider()

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transitória")
        return self._mock.execute(agent, task)


def test_execution_metrics_counts_retries_and_duration() -> None:
    svc = OrchestrationService(provider=FlakyProvider())
    orch = svc.create_orchestration("backend X")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)

    em = MetricsService(svc).execution_metrics(orch.id)
    assert em["agent_executions"] == 1
    assert em["retries"] == 1
    assert em["failures"] == 0
    assert em["avg_ms"] >= 0.0


def test_prometheus_and_aggregate_include_execution_counters() -> None:
    svc = OrchestrationService(provider=FlakyProvider())
    orch = svc.create_orchestration("backend X")
    svc.run_card(orch.id, svc.get_cards(orch.id)[0].id)

    agg = svc.aggregate_metrics()
    assert agg["agent_retries"] == 1
    body = MetricsService(svc).prometheus()
    assert "aso_agent_retries_total 1" in body

    client = TestClient(create_app(svc))
    exec_api = client.get(f"/v1/orchestrations/{orch.id}/execution-metrics").json()
    assert exec_api["retries"] == 1
