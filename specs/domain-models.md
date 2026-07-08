# SPEC — Modelos de domínio (Pydantic + tabelas)

- **Card:** TASK-02
- **Épico:** EPIC-2 (Domínio & Contexto)
- **Fase:** F5
- **ADRs:** ADR-0005
- **Requisitos:** §29, §40 Task 2
- **Depende de:** TASK-01

## Objetivo

Implementar as entidades canônicas do domínio do ASO Runtime, tanto como schemas Pydantic v2 (validação, DTOs, contexto) quanto como tabelas relacionais SQLAlchemy 2.x + migrations Alembic. Estas entidades são o vocabulário compartilhado por todos os planes e a base de rastreabilidade requisito → decisão → task → implementação.

Segue o modelo de dados de [`docs/domain-model.md`](../docs/domain-model.md) (agregados por plane) e a lista de tabelas do §29. Consistência forte por orquestração (ADR-0005). Toda entidade relevante tem `id` (UUID) e `created_at`/`updated_at` (ISO8601 UTC), conforme §39.9.

## Escopo

- Incluído (entidades §40 Task 2):
  - `Project`, `Orchestration`, `Phase`, `ExecutionPlan` (com `PlannedAgent`).
  - `Board`, `BoardColumn`, `KanbanCard`, `CardDependency`, `CardEvent`.
  - `Agent`, `AgentRun`.
  - `OrchestratorContext` (schema — persistência detalhada em [orchestrator-context.md](orchestrator-context.md)).
  - `ContextPatch`, `Conflict`, `QualityGateResult`, `Snapshot`, `ADR`, `HumanApproval`.
  - Enums de domínio: `execution_mode`, `phase code` (F1..F7), `snapshot_version` (O0..O7), status por entidade, `card type`, `priority`, `assignee_type`, `strategy`, `risk_level`, `patch_type`, `conflict type`.
  - Schemas Pydantic (Base/Create/Read) + modelos ORM + migração Alembic inicial.
- Fora de escopo (MVP-1):
  - `Worktree`, `PullRequest`, `CIEvent`, `ReviewEvent` (execução real — MVP-3+).
  - `AgentMessage`, `AgentToolCall`, `AgentOutput`, `ProviderConfig`, `CliAgentConfig`, `AgentRoleBinding`, `AgentExecutionSelection` (configuração multi-provider — MVP posterior; podem ter stubs).
  - Regras de negócio complexas (ficam nos serviços das respectivas specs).

## Comportamento esperado

- Todo agregado possui `id: UUID` gerado no servidor e `created_at`/`updated_at` (quando aplicável) em UTC.
- Schemas Pydantic v2 validam entrada/saída; campos enum recusam valores fora do domínio.
- Modelos ORM mapeiam para as tabelas do §29; relacionamentos-chave do domain-model são declarados (ex.: `Orchestration 1—1 OrchestratorContext`, `Board 1—N BoardColumn/KanbanCard`, `AgentRun N—1 Agent`).
- `KanbanCard` inclui os campos de rastreabilidade (§16.5): `linked_requirements[]`, `linked_adrs[]`, `linked_contracts[]`, `linked_files[]`, `linked_prs[]`, `acceptance_criteria[]`, `dependencies[]`, `blocked_by[]`.
- `ADR.id` é `ADR-XXXX` (string), não UUID. Demais IDs são UUID.
- Migração Alembic cria todas as tabelas do escopo e roda `upgrade`/`downgrade` sem erro.

## Contratos / Interfaces

Módulos: schemas em `src/aso/shared/schemas/`; ORM em `src/aso/db/models/`.

```python
# src/aso/shared/schemas/orchestration.py
class OrchestrationBase(BaseModel):
    project_id: UUID
    execution_mode: ExecutionMode  # full-pipeline | feature-evolution | ...
    user_request: str

class Orchestration(OrchestrationBase):
    id: UUID
    current_phase: PhaseCode        # F1..F7
    snapshot_version: SnapshotVersion  # O0..O7
    status: OrchestrationStatus     # created|running|blocked|waiting_human|completed|cancelled|rolled_back
    created_at: datetime
    updated_at: datetime

# src/aso/shared/schemas/kanban.py
class KanbanCard(BaseModel):
    id: UUID
    board_id: UUID
    orchestration_id: UUID
    phase: PhaseCode
    type: CardType
    title: str
    status: str
    priority: Priority
    assignee_type: AssigneeType
    assignee: str | None
    agents: list[str] = []
    dependencies: list[UUID] = []
    blocked_by: list[UUID] = []
    acceptance_criteria: list[str] = []
    linked_requirements: list[str] = []
    linked_adrs: list[str] = []
    # ... linked_contracts, linked_files, linked_prs, worktree, branch, quality_gate, context_snapshot
    created_at: datetime
    updated_at: datetime
```

- ORM base declarativa em `src/aso/db/base.py` com mixin `id/created_at/updated_at`.
- Enums centralizados em `src/aso/shared/enums.py`.

## Critérios de aceite

- [ ] Todas as entidades do escopo possuem `id` + timestamps.
- [ ] Schemas Pydantic validam dados corretos e rejeitam enums/campos inválidos.
- [ ] Migrations Alembic criadas geram todas as tabelas do §29 (escopo MVP-1) e revertem sem erro.
- [ ] Relacionamentos-chave do domain-model.md declarados no ORM.

## Rastreabilidade

§29/§40 Task 2 → ADR-0005 → esta spec → TASK-02 → `src/aso/shared/schemas/*`, `src/aso/db/models/*`, `migrations/versions/*` → `tests/unit/test_schemas.py`, `tests/integration/test_migrations.py`
