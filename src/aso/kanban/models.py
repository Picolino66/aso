"""Modelos do Kanban Plane (§16.5)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from aso.shared.ids import gen_id, now_iso
from aso.shared.types import AssigneeType, CardType, ColumnKey, Phase, RiskLevel


class BoardColumn(BaseModel):
    key: ColumnKey
    order: int
    wip_limit: int | None = None


class KanbanCard(BaseModel):
    """Unidade de trabalho rastreável (§16.5)."""

    id: str = Field(default_factory=lambda: gen_id("card"))
    board_id: str
    orchestration_id: str
    phase: Phase
    type: CardType
    title: str
    description: str = ""
    status: ColumnKey = ColumnKey.BACKLOG
    priority: RiskLevel = RiskLevel.MEDIUM
    assignee_type: AssigneeType = AssigneeType.AGENT
    assignee: str | None = None
    agents: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    linked_requirements: list[str] = Field(default_factory=list)
    linked_adrs: list[str] = Field(default_factory=list)
    linked_contracts: list[str] = Field(default_factory=list)
    linked_files: list[str] = Field(default_factory=list)
    linked_prs: list[str] = Field(default_factory=list)
    worktree: str | None = None
    branch: str | None = None
    block_reason: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class Board(BaseModel):
    id: str = Field(default_factory=lambda: gen_id("board"))
    orchestration_id: str
    project_id: str | None = None
    name: str
    scope: str = "orchestration"
    columns: list[BoardColumn] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class CardEvent(BaseModel):
    id: str = Field(default_factory=lambda: gen_id("cardevt"))
    card_id: str
    type: str
    from_status: ColumnKey | None = None
    to_status: ColumnKey | None = None
    actor: str = "system"
    created_at: str = Field(default_factory=now_iso)
