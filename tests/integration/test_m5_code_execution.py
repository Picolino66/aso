"""(M5) Execução de código real: provider roteado por fase + gate rodando testes."""

from __future__ import annotations

from typing import Any

import pytest

from aso.agents.models import AgentOutput, AgentSpec
from aso.control.orchestration_service import OrchestrationService
from aso.execution.routing_provider import RoutingExecutionProvider
from aso.shared.types import Phase


class _StubProvider:
    def __init__(self, pid: str) -> None:
        self.id = pid
        self.seen: list[str] = []

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        self.seen.append(str(task.get("phase")))
        return AgentOutput(agent_role=agent.role, executor_id=self.id, summary=self.id)


def test_router_sends_planning_to_planner_and_code_to_coder() -> None:
    planner, coder = _StubProvider("planner"), _StubProvider("coder")
    router = RoutingExecutionProvider(planner=planner, coder=coder)
    agent = AgentSpec(role="X")

    router.execute(agent, {"phase": "F2"})  # planejamento
    router.execute(agent, {"phase": "F5"})  # código
    router.execute(agent, {"phase": "F6"})  # código

    assert planner.seen == ["F2"]
    assert coder.seen == ["F5", "F6"]


def test_router_falls_back_to_single_provider() -> None:
    only = _StubProvider("solo")
    router = RoutingExecutionProvider(planner=only)
    router.execute(AgentSpec(role="X"), {"phase": "F5"})  # sem coder → usa o planner
    assert only.seen == ["F5"]


def test_router_requires_at_least_one() -> None:
    with pytest.raises(ValueError, match="ao menos um"):
        RoutingExecutionProvider()


def test_code_gate_blocks_on_failing_tests(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ASO_TARGET_REPO", str(tmp_path))
    monkeypatch.setenv("ASO_GATE_TEST_COMMAND", "bash -c 'exit 1'")  # suíte vermelha
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)

    result = svc.run_phase(orch.id, Phase.F5)  # gate de código roda em F5
    assert result["gate_status"] == "FAILED"  # testes vermelhos reprovam o gate
    assert result["approval_id"] is None  # sem aprovação → não avança
    assert result["snapshot"] is None


def test_code_gate_passes_on_green_tests(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ASO_TARGET_REPO", str(tmp_path))
    monkeypatch.setenv("ASO_GATE_TEST_COMMAND", "bash -c 'exit 0'")  # suíte verde
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)

    result = svc.run_phase(orch.id, Phase.F5)
    assert result["gate_status"] == "PASSED"
    assert result["approval_id"]  # aprovação de avanço aberta
