"""(a) AgentSupervisor (retry/nudge), execução concorrente e falha → card Failed."""

from __future__ import annotations

from typing import Any

from aso.agents.executor import LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.control.models import DecisionInput
from aso.control.orchestration_service import OrchestrationService


class FlakyProvider:
    """Falha as primeiras `fail_times` chamadas, depois delega ao mock."""

    id = "flaky"

    def __init__(self, fail_times: int = 1) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self._mock = LocalMockExecutionProvider()

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("falha transitória")
        return self._mock.execute(agent, task)


class AlwaysFailProvider:
    id = "fail"

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        raise RuntimeError("falha permanente")


def test_supervisor_retries_and_succeeds() -> None:
    svc = OrchestrationService(provider=FlakyProvider(fail_times=1))
    orch = svc.create_orchestration("backend X")
    card = svc.get_cards(orch.id)[0]
    results = svc.run_card(orch.id, card.id)
    assert results and results[0].status.value == "applied"
    assert svc.get_cards(orch.id)[0].status.value == "Testing"
    types = {e.type for e in svc.timeline(orch.id)}
    assert "AgentRetry" in types and "AgentRetrySucceeded" in types


def test_terminal_failure_moves_card_to_failed() -> None:
    svc = OrchestrationService(provider=AlwaysFailProvider())
    orch = svc.create_orchestration("backend X")
    card = svc.get_cards(orch.id)[0]
    results = svc.run_card(orch.id, card.id)
    assert results == []
    assert svc.get_cards(orch.id)[0].status.value == "Failed"
    assert any(e.type == "AgentFailed" for e in svc.timeline(orch.id))


def test_concurrent_run_plan_waves() -> None:
    svc = OrchestrationService()  # mock estável (thread-safe)
    orch = svc.create_orchestration(
        "feature ampla",
        decision_input=DecisionInput(
            user_request="f", domains=["backend", "frontend"], parallelizable=True
        ),
    )
    result = svc.run_plan(orch.id, concurrent=True)
    assert result["concurrent"] is True
    assert result["waves"] >= 2  # workers em uma onda, ReviewAgent em outra
    assert result["count"] == len(svc.get_plan(orch.id).agents)
    assert all(c.status.value == "Testing" for c in svc.get_cards(orch.id))
