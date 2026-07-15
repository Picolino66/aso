"""Modelos do Control Plane (§14)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from aso.shared.ids import gen_id, now_iso
from aso.shared.types import ExecutionMode, ExecutionStrategy, Phase, ProjectStatus, RiskLevel


class Project(BaseModel):
    """Projeto do catálogo multi-repo; agrupa orquestrações sem possuí-las."""

    id: str = Field(default_factory=lambda: gen_id("proj"))
    name: str
    description: str = ""
    target_path: str | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    archived_at: str | None = None


class ProjectEvent(BaseModel):
    """Evento append-only para auditar o ciclo de vida de um projeto."""

    id: str = Field(default_factory=lambda: gen_id("projevt"))
    project_id: str
    type: str
    actor: str
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class Orchestration(BaseModel):
    """Instância de uma orquestração (§17)."""

    id: str = Field(default_factory=lambda: gen_id("orch"))
    project_id: str | None = None
    # Pasta de trabalho desta orquestração (workspace): onde os agentes CLI criam
    # código e rodam gates, substituindo o `ASO_TARGET_REPO` global só para ela.
    # `None` → cai no comportamento legado (env/provider global).
    target_path: str | None = None
    # Configuração efetiva da execução, preservada para a UI não exibir um default falso.
    selected_executor: str | None = None
    selected_effort: str | None = None
    validation_command: str | None = None
    workspace_prepared: bool = False
    execution_mode: ExecutionMode = ExecutionMode.FULL_PIPELINE
    # A esteira começa em F1 (discovery) e avança até F7 sob o autopilot.
    current_phase: Phase = Phase.F1
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
