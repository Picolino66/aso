"""Modelos do Kanban Plane (§16.5)."""

from __future__ import annotations

from typing import Any

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
    # Papel planejado (ex.: "BackendDevelopmentAgent") continua em `assignee`; este
    # campo guarda o PERFIL de executor que de fato rodou (ex.: "codex-gpt-5-high"),
    # gravado em `_apply_execution` — sem ele não há como exigir revisor diferente
    # do implementador (§14, ADR-0017). Serve também ao §23/§24 (modelos utilizados).
    executor: str | None = None
    agents: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    # Hierarquia épico → história → subtarefa (§7 do fluxo.md, ADR-0025). Nulo (o
    # estado de todo card anterior a esta ADR) continua válido — a hierarquia é
    # opcional, não obrigatória. Profundidade máxima 3 e ausência de ciclo são
    # validadas em `BoardService.add_card`, não aqui (Pydantic não valida contra
    # outros cards).
    parent_id: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    # Ações objetivas de uma revisão reprovada (§15, ADR-0017): só as de severidade
    # `obrigatoria` — chegam ao agente na re-execução via `_build_task`. Limpo quando
    # o veredito volta a ser aprovado.
    correction_actions: list[str] = Field(default_factory=list)
    # Ring das últimas 5 falhas (§13 do fluxo.md, ADR-0019) — cada item é um
    # `FailureRecord.model_dump()` (control/failure.py). Fica em `kanban/` como dict
    # solto (não o tipo Pydantic) para não inverter a dependência: `control` importa
    # `kanban`, não o contrário.
    failures: list[dict[str, Any]] = Field(default_factory=list)
    # Ring das últimas 10 verificações de QA manual (§16/§17 do fluxo.md, ADR-0025) —
    # cada item é um `QaCheck.model_dump()` (control/qa.py). Mesmo raciocínio de
    # `failures`: dict solto para não inverter a dependência `control` → `kanban`.
    qa_checks: list[dict[str, Any]] = Field(default_factory=list)
    # Consumo acumulado do agente neste card (§1.1/§1.4, ADR-0026) — soma reexecuções
    # (`aso.shared.agent_usage.acumular_uso`). Dict solto (não `UsoDoAgente`) pelo
    # mesmo motivo de `failures`/`qa_checks`: `kanban` não importa `control`, e o tipo
    # já pertence a `shared`, mais neutro que qualquer um dos dois.
    uso: dict[str, Any] = Field(default_factory=dict)
    # Ficha de encerramento (§23 do fluxo.md, ADR-0021) — preenchida em `merge_pr`,
    # o ponto em que o card chega a Done. Vazio = card ainda não encerrado (ou
    # encerrado antes desta ADR). Só registra o que o runtime tem à mão: campos do
    # §23 sem dado disponível (data de implantação, commits individuais) ficam de
    # fora — ficha com campo inventado é pior que ficha curta.
    closure: dict[str, Any] = Field(default_factory=dict)
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
    """Movimentação de um card (§8 do fluxo.md): cada uma registra motivo, resultado,
    evidências e próxima ação — não só data e ator (ADR-0019)."""

    id: str = Field(default_factory=lambda: gen_id("cardevt"))
    card_id: str
    type: str
    from_status: ColumnKey | None = None
    to_status: ColumnKey | None = None
    actor: str = "system"
    reason: str = ""
    result: str = ""
    evidence: list[str] = Field(default_factory=list)
    next_action: str = ""
    created_at: str = Field(default_factory=now_iso)
