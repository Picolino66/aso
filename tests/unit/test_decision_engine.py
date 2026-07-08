"""Testes do MultiAgentDecisionEngine (TASK-06, §14)."""

from __future__ import annotations

from aso.control.decision_engine import MultiAgentDecisionEngine
from aso.control.models import DecisionInput
from aso.shared.types import ExecutionStrategy, RiskLevel


def test_single_agent_for_simple_task() -> None:
    d = MultiAgentDecisionEngine().decide(
        DecisionInput(user_request="ajuste simples", domains=["backend"])
    )
    assert d.execution_mode == ExecutionStrategy.SINGLE_AGENT
    assert len(d.agents) == 1
    assert not d.requires_human_approval


def test_parallel_for_independent_multidomain() -> None:
    d = MultiAgentDecisionEngine().decide(
        DecisionInput(
            user_request="feature ampla", domains=["backend", "frontend"], parallelizable=True
        )
    )
    assert d.execution_mode == ExecutionStrategy.PARALLEL
    assert any(a.agent == "ReviewAgent" for a in d.agents)


def test_sequential_for_dependent_multidomain() -> None:
    d = MultiAgentDecisionEngine().decide(
        DecisionInput(user_request="feature", domains=["backend", "database"])
    )
    assert d.execution_mode == ExecutionStrategy.SEQUENTIAL


def test_critical_requires_human_approval() -> None:
    d = MultiAgentDecisionEngine().decide(
        DecisionInput(user_request="deploy prod", domains=["devops"], risk_level=RiskLevel.CRITICAL)
    )
    assert d.requires_human_approval


def test_deploy_impact_requires_approval() -> None:
    d = MultiAgentDecisionEngine().decide(
        DecisionInput(user_request="publicar", domains=["backend"], impacts=["deploy"])
    )
    assert d.requires_human_approval
