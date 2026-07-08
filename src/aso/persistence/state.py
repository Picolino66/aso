"""Estado serializável de uma orquestração (aggregate snapshot).

Captura tudo que precisa sobreviver entre execuções. É serializado como JSON e
persistido pelo repositório; na leitura, o OrchestrationService o reidrata nos
serviços de domínio.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from aso.control.models import ExecutionPlan, Orchestration
from aso.governance.models import (
    ADR,
    Conflict,
    ContextPatch,
    HumanApproval,
    PullRequest,
    QualityGateResult,
    Snapshot,
)
from aso.kanban.models import Board, CardEvent, KanbanCard


class OrchestrationState(BaseModel):
    """Snapshot completo e serializável do aggregate de uma orquestração."""

    orchestration: Orchestration
    plan: ExecutionPlan

    context_payload: dict[str, Any] = Field(default_factory=dict)
    context_version: int = 0
    context_frozen: list[str] = Field(default_factory=list)
    context_history: list[dict[str, Any]] = Field(default_factory=list)

    adrs: list[ADR] = Field(default_factory=list)
    snapshots: list[Snapshot] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gate_results: list[QualityGateResult] = Field(default_factory=list)
    approvals: list[HumanApproval] = Field(default_factory=list)
    patches: list[ContextPatch] = Field(default_factory=list)
    pull_requests: list[PullRequest] = Field(default_factory=list)

    board: Board
    cards: list[KanbanCard] = Field(default_factory=list)
    card_events: list[CardEvent] = Field(default_factory=list)

    events: list[dict[str, Any]] = Field(default_factory=list)
