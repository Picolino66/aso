"""Modelos do Control Plane (§14)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from aso.shared.ids import gen_id, now_iso
from aso.shared.types import ExecutionMode, ExecutionStrategy, Phase, RiskLevel


class Orchestration(BaseModel):
    """Instância de uma orquestração (§17)."""

    id: str = Field(default_factory=lambda: gen_id("orch"))
    project_id: str | None = None
    execution_mode: ExecutionMode = ExecutionMode.FULL_PIPELINE
    current_phase: Phase = Phase.F5
    snapshot_version: str = "O0"
    status: str = "created"
    user_request: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class DecisionInput(BaseModel):
    """Entrada do MultiAgentDecisionEngine (§14)."""

    user_request: str
    current_phase: Phase = Phase.F4
    risk_level: RiskLevel = RiskLevel.LOW
    domains: list[str] = Field(default_factory=list)
    parallelizable: bool = False
    needs_independent_review: bool = False
    impacts: list[str] = Field(
        default_factory=list, description="Ex.: architecture, contract, security, database, deploy"
    )


class PlannedAgent(BaseModel):
    agent: str
    role: str = "primary"
    reason: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    parallel_group: str | None = None


class MultiAgentDecision(BaseModel):
    """Saída do MultiAgentDecisionEngine (§14)."""

    execution_mode: ExecutionStrategy
    reason: str
    risk_level: RiskLevel
    requires_human_approval: bool = False
    agents: list[PlannedAgent] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    fallback_strategy: str = ""


class ExecutionPlan(BaseModel):
    """Plano de execução de uma orquestração (§14, domain-model)."""

    id: str = Field(default_factory=lambda: gen_id("plan"))
    orchestration_id: str
    execution_mode: ExecutionMode
    strategy: ExecutionStrategy
    reason: str
    risk_level: RiskLevel
    requires_human_approval: bool = False
    agents: list[PlannedAgent] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    fallback_strategy: str = ""
    created_at: str = Field(default_factory=now_iso)
