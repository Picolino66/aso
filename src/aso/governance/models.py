"""Modelos de domínio da governança (Pydantic v2).

Materializa as entidades §17–§24 do requisito. Todas com `id` e timestamps.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from aso.shared.ids import gen_id, now_iso
from aso.shared.types import (
    ADRStatus,
    ConflictType,
    GateStatus,
    PatchStatus,
    PatchType,
    Phase,
)


class ContextPatch(BaseModel):
    """Proposta de alteração no contexto (§18). Produzida por agentes/skills."""

    id: str = Field(default_factory=lambda: gen_id("patch"))
    orchestration_id: str
    card_id: str | None = None
    agent: str
    phase: Phase
    patch_type: PatchType
    target_path: str = Field(min_length=1, description="Caminho pontilhado no contexto")
    content: Any = None
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    requires_adr: bool = False
    requires_approval: bool = False
    linked_adrs: list[str] = Field(default_factory=list)
    status: PatchStatus = PatchStatus.PENDING
    created_at: str = Field(default_factory=now_iso)


class Conflict(BaseModel):
    """Conflito detectado pelo ContextBus/ConflictDetector (§20)."""

    id: str = Field(default_factory=lambda: gen_id("conflict"))
    orchestration_id: str
    type: ConflictType
    source_patch_ids: list[str] = Field(default_factory=list)
    description: str
    resolution: str | None = None
    status: str = "open"
    created_at: str = Field(default_factory=now_iso)


class GateCriterionResult(BaseModel):
    """Resultado de um critério individual de um quality gate."""

    name: str
    status: GateStatus
    evidence: list[str] = Field(default_factory=list)
    failure_reason: str | None = None


class QualityGateResult(BaseModel):
    """Resultado de um quality gate (§22)."""

    id: str = Field(default_factory=lambda: gen_id("gate"))
    orchestration_id: str
    phase: Phase
    status: GateStatus
    criteria: list[GateCriterionResult] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    approved_by: str | None = None
    created_at: str = Field(default_factory=now_iso)


class Snapshot(BaseModel):
    """Versão congelada do contexto após uma fase aprovada (§23)."""

    id: str = Field(default_factory=lambda: gen_id("snapshot"))
    orchestration_id: str
    snapshot_version: str
    phase: Phase
    context_hash: str
    frozen_sections: list[str] = Field(default_factory=list)
    quality_gate_result_id: str | None = None
    adrs: list[str] = Field(default_factory=list)
    cards: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class HumanApproval(BaseModel):
    """Solicitação de aprovação humana para ação crítica (§24)."""

    id: str = Field(default_factory=lambda: gen_id("approval"))
    orchestration_id: str
    card_id: str | None = None
    requested_by_agent: str = "OrchestratorAgent"
    action: str
    risk: str = "medium"
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    status: str = "pending"
    approved_by: str | None = None
    created_at: str = Field(default_factory=now_iso)


class PullRequest(BaseModel):
    """Pull Request derivado do worktree de um card (§26, MVP-4)."""

    id: str = Field(default_factory=lambda: gen_id("pr"))
    orchestration_id: str
    card_id: str | None = None
    branch: str
    base_branch: str = "main"
    title: str = ""
    status: str = "open"  # open | merged | closed
    ci_status: str = "pending"  # pending | passed | failed
    review_status: str = "pending"  # pending | approved | changes_requested
    created_at: str = Field(default_factory=now_iso)
    merged_at: str | None = None


class CandidateRun(BaseModel):
    """Resultado rastreável de uma corrida de candidatos CLI por card (§26A.6).

    Registra os candidatos avaliados (executor, branch, diff, arquivos, erro) e o
    branch recomendado pela heurística, formando um histórico auditável de corridas.
    """

    id: str = Field(default_factory=lambda: gen_id("race"))
    orchestration_id: str
    card_id: str
    recommended_branch: str | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class ADR(BaseModel):
    """Architecture Decision Record (§21)."""

    id: str
    orchestration_id: str
    title: str
    status: ADRStatus = ADRStatus.PROPOSED
    context: str = ""
    options_considered: list[dict[str, Any]] = Field(default_factory=list)
    decision: str = ""
    rationale: str = ""
    tradeoffs: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    phase: Phase
    created_by_agent: str | None = None
    reviewed_by_agent: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    linked_cards: list[str] = Field(default_factory=list)
    linked_requirements: list[str] = Field(default_factory=list)
    locked_paths: list[str] = Field(
        default_factory=list,
        description="Caminhos do contexto governados por esta ADR (override exige referenciá-la)",
    )
    timestamp: str = Field(default_factory=now_iso)
