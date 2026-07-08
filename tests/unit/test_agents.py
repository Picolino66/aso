"""Testes do Agent Plane (TASK-07, TASK-08)."""

from __future__ import annotations

from aso.agents.executor import AgentExecutor, LocalMockExecutionProvider
from aso.agents.registry import AgentRegistry
from aso.shared.types import Phase


def test_seed_defaults_registers_16_agents() -> None:
    reg = AgentRegistry()
    reg.seed_defaults()
    assert len(reg.list_all()) == 16
    assert reg.get("BackendDevelopmentAgent") is not None
    pmap = reg.permission_map()
    assert "engineering" in pmap["BackendDevelopmentAgent"]


def test_mock_executor_returns_structured_output_with_patch() -> None:
    reg = AgentRegistry()
    reg.seed_defaults()
    agent = reg.get("ArchitectureDesignAgent")
    assert agent is not None
    executor = AgentExecutor(provider=LocalMockExecutionProvider())
    output = executor.run(
        agent,
        {
            "orchestration_id": "orch_x",
            "phase": Phase.F2.value,
            "target_path": "architecture.pattern",
            "content": "modular-monolith",
        },
    )
    assert output.executor_id == "local_mock"
    assert len(output.patches) == 1
    assert output.patches[0].target_path == "architecture.pattern"
    assert output.patches[0].agent == "ArchitectureDesignAgent"
