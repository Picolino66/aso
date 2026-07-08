"""ExecutionPlanner (§14, TASK-05).

Gera um ExecutionPlan a partir de uma solicitação e da decisão multiagente.
"""

from __future__ import annotations

from aso.control.decision_engine import MultiAgentDecisionEngine
from aso.control.models import DecisionInput, ExecutionPlan
from aso.shared.types import ExecutionMode


class ExecutionPlanner:
    """Constrói o plano de execução da orquestração."""

    def __init__(self, decision_engine: MultiAgentDecisionEngine | None = None) -> None:
        self.decision_engine = decision_engine or MultiAgentDecisionEngine()

    def plan(
        self, orchestration_id: str, execution_mode: ExecutionMode, decision_input: DecisionInput
    ) -> ExecutionPlan:
        decision = self.decision_engine.decide(decision_input)
        return ExecutionPlan(
            orchestration_id=orchestration_id,
            execution_mode=execution_mode,
            strategy=decision.execution_mode,
            reason=decision.reason,
            risk_level=decision.risk_level,
            requires_human_approval=decision.requires_human_approval,
            agents=decision.agents,
            success_criteria=decision.success_criteria,
            fallback_strategy=decision.fallback_strategy,
        )
