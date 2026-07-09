"""Modelos SQLAlchemy normalizados (§29, ADR-0006).

Normalização estrita: coleções de valor viram tabelas de junção (`board_columns`,
`card_links`, `adr_links`, `planned_agents`, `adr_options`, `gate_criteria`) e a
tabela genérica `value_items` (listas planas: success_criteria, frozen_sections,
ids de snapshot/conflict, blocking/warnings/required de gate). O payload do
OrchestratorContext permanece JSONB no Postgres (ADR-0005); restam em JSON apenas
payloads livres (contexto/eventos/approval) e sublistas de opção (pros/cons).
A tabela `adrs` tem PK composta `(orchestration_id, id)` — ids são sequenciais por
orquestração. Índices em FKs e nos campos consultados.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSON portável: JSONB no PostgreSQL, JSON genérico nos demais.
_JSONB = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Base declarativa do ORM."""


class OrchestrationRow(Base):
    __tablename__ = "orchestrations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Pasta de trabalho da orquestração (workspace); NULL = legado (repo global).
    target_path: Mapped[str | None] = mapped_column(String, nullable=True)
    execution_mode: Mapped[str] = mapped_column(String)
    current_phase: Mapped[str] = mapped_column(String)
    snapshot_version: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    user_request: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String, index=True)
    updated_at: Mapped[str] = mapped_column(String)


class ContextRow(Base):
    __tablename__ = "orchestrator_contexts"

    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    context_hash: Mapped[str] = mapped_column(String, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict)


class ContextHistoryRow(Base):
    __tablename__ = "context_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    patch_id: Mapped[str] = mapped_column(String)
    agent: Mapped[str] = mapped_column(String)
    target_path: Mapped[str] = mapped_column(String)
    patch_type: Mapped[str] = mapped_column(String)
    context_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)


class ExecutionPlanRow(Base):
    __tablename__ = "execution_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"), index=True)
    execution_mode: Mapped[str] = mapped_column(String)
    strategy: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text, default="")
    risk_level: Mapped[str] = mapped_column(String)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_strategy: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String)


class PlannedAgentRow(Base):
    """Agente planejado dentro de um ExecutionPlan (tabela de junção)."""

    __tablename__ = "planned_agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("execution_plans.id"), index=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    position: Mapped[int] = mapped_column(Integer)
    agent: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="primary")
    reason: Mapped[str] = mapped_column(Text, default="")
    parallel_group: Mapped[str | None] = mapped_column(String, nullable=True)
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)


class BoardRow(Base):
    __tablename__ = "boards"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String, default="orchestration")
    created_at: Mapped[str] = mapped_column(String)


class BoardColumnRow(Base):
    """Coluna de um board (§29 board_columns)."""

    __tablename__ = "board_columns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    key: Mapped[str] = mapped_column(String)
    position: Mapped[int] = mapped_column(Integer)
    wip_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CardRow(Base):
    __tablename__ = "kanban_cards"
    __table_args__ = (Index("ix_cards_orch_status", "orchestration_id", "status"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    phase: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String)
    priority: Mapped[str] = mapped_column(String)
    assignee_type: Mapped[str] = mapped_column(String)
    assignee: Mapped[str | None] = mapped_column(String, nullable=True)
    worktree: Mapped[str | None] = mapped_column(String, nullable=True)
    branch: Mapped[str | None] = mapped_column(String, nullable=True)
    block_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)


class CardLinkRow(Base):
    """Coleções de valor de um card, normalizadas (rel = nome da coleção)."""

    __tablename__ = "card_links"
    __table_args__ = (
        Index("ix_card_links_card_rel", "card_id", "rel"),
        Index("ix_card_links_orch_rel_value", "orchestration_id", "rel", "value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("kanban_cards.id"))
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    rel: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(String)
    position: Mapped[int] = mapped_column(Integer, default=0)


class CardEventRow(Base):
    __tablename__ = "card_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"), index=True)
    card_id: Mapped[str] = mapped_column(String, index=True)
    type: Mapped[str] = mapped_column(String)
    from_status: Mapped[str | None] = mapped_column(String, nullable=True)
    to_status: Mapped[str | None] = mapped_column(String, nullable=True)
    actor: Mapped[str] = mapped_column(String, default="system")
    created_at: Mapped[str] = mapped_column(String)


class AdrRow(Base):
    __tablename__ = "adrs"
    __table_args__ = (Index("ix_adrs_orch_status", "orchestration_id", "status"),)

    # ADR ids (ADR-0001...) são sequenciais POR orquestração — PK composta.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"), primary_key=True)
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    context: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    phase: Mapped[str] = mapped_column(String)
    created_by_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_by_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    supersedes: Mapped[str | None] = mapped_column(String, nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp: Mapped[str] = mapped_column(String)


class AdrOptionRow(Base):
    """Opção considerada em uma ADR (options_considered, normalizada)."""

    __tablename__ = "adr_options"
    __table_args__ = (Index("ix_adr_options_adr", "adr_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    adr_id: Mapped[str] = mapped_column(String)  # referência leve (ADR-XXXX por orquestração)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)
    pros: Mapped[list[str]] = mapped_column(JSON, default=list)
    cons: Mapped[list[str]] = mapped_column(JSON, default=list)


class AdrLinkRow(Base):
    """Coleções de valor planas de uma ADR (tradeoffs, consequences, links)."""

    __tablename__ = "adr_links"
    __table_args__ = (Index("ix_adr_links_adr_rel", "adr_id", "rel"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    adr_id: Mapped[str] = mapped_column(String)  # referência leve (ADR-XXXX por orquestração)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    rel: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)


class SnapshotRow(Base):
    __tablename__ = "snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"), index=True)
    snapshot_version: Mapped[str] = mapped_column(String)
    phase: Mapped[str] = mapped_column(String)
    context_hash: Mapped[str] = mapped_column(String)
    quality_gate_result_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict)


class ConflictRow(Base):
    __tablename__ = "conflicts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"), index=True)
    type: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="open")
    created_at: Mapped[str] = mapped_column(String)


class QualityGateResultRow(Base):
    __tablename__ = "quality_gate_results"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"), index=True)
    phase: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String)


class GateCriterionRow(Base):
    """Critério de um quality gate (normalizado)."""

    __tablename__ = "gate_criteria"
    __table_args__ = (Index("ix_gate_criteria_gate", "gate_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gate_id: Mapped[str] = mapped_column(ForeignKey("quality_gate_results.id"))
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)


class ValueItemRow(Base):
    """Coleção de valor plana genérica (listas de strings de qualquer entidade)."""

    __tablename__ = "value_items"
    __table_args__ = (Index("ix_value_items_owner", "owner_type", "owner_id", "rel"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"), index=True)
    owner_type: Mapped[str] = mapped_column(String)
    owner_id: Mapped[str] = mapped_column(String)
    rel: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)


class HumanApprovalRow(Base):
    __tablename__ = "human_approvals"
    __table_args__ = (Index("ix_approvals_orch_status", "orchestration_id", "status"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    card_id: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_by_agent: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    risk: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ContextPatchRow(Base):
    """ContextPatch submetido ao ContextBus (trilha de auditoria, §18)."""

    __tablename__ = "context_patches"
    __table_args__ = (Index("ix_patches_orch_status", "orchestration_id", "status"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    card_id: Mapped[str | None] = mapped_column(String, nullable=True)
    agent: Mapped[str] = mapped_column(String)
    phase: Mapped[str] = mapped_column(String)
    patch_type: Mapped[str] = mapped_column(String)
    target_path: Mapped[str] = mapped_column(String)
    content: Mapped[Any] = mapped_column(JSON, nullable=True)
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    linked_adrs: Mapped[list[str]] = mapped_column(JSON, default=list)
    requires_adr: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)


class PullRequestRow(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (Index("ix_pulls_orch_status", "orchestration_id", "status"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    card_id: Mapped[str | None] = mapped_column(String, nullable=True)
    branch: Mapped[str] = mapped_column(String)
    base_branch: Mapped[str] = mapped_column(String, default="main")
    title: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String)
    ci_status: Mapped[str] = mapped_column(String)
    review_status: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)
    merged_at: Mapped[str | None] = mapped_column(String, nullable=True)


class CandidateRunRow(Base):
    __tablename__ = "candidate_runs"
    __table_args__ = (Index("ix_candidate_runs_orch_card", "orchestration_id", "card_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    card_id: Mapped[str] = mapped_column(String)
    recommended_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String)


class SloEvaluationRow(Base):
    __tablename__ = "slo_evaluations"
    __table_args__ = (Index("ix_slo_evals_orch_created", "orchestration_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    fail_rate: Mapped[float] = mapped_column(Float, default=0.0)
    burn_rate: Mapped[float] = mapped_column(Float, default=0.0)
    consumed_pct: Mapped[float] = mapped_column(Float, default=0.0)
    severity: Mapped[str] = mapped_column(String, default="ok")
    breaches: Mapped[list[str]] = mapped_column(JSON, default=list)
    alerts_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String)


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_orch_seq", "orchestration_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    orchestration_id: Mapped[str] = mapped_column(ForeignKey("orchestrations.id"))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String)
