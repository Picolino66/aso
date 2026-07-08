# SPEC — Kanban básico (board, colunas, cards) + automação

- **Card:** TASK-04
- **Épico:** EPIC-3 (Kanban básico)
- **Fase:** F5
- **ADRs:** ADR-0002
- **Requisitos:** §16, §40 Task 4
- **Depende de:** TASK-02

## Objetivo

Implementar o Kanban como plano de execução operacional do runtime (§8.7, ADR-0002), não como mera visualização. Entrega boards, colunas, cards e a máquina de estados dirigida por eventos (§16.7) que move cards automaticamente conforme o andamento real da execução.

Cada card é uma unidade de trabalho rastreável (§16.5) vinculada a fase, agente, contexto e artefatos. O Kanban deve refletir o estado real da execução (§39.14).

## Escopo

- Incluído:
  - `Board` com `scope` (project|orchestration|phase|release|feature) e `swimlane_by`.
  - `BoardColumn` com as 12 colunas obrigatórias (§16.2): Backlog, Ready, Planning, InProgress, WaitingAgent, WaitingHuman, Review, Testing, Blocked, Failed, Done, Archived; `order` e `wip_limit?`.
  - `KanbanCard` com tipos §16.4 (Epic, Feature, Task, Bug, TechDebt, ADRTask, Research, Review, Test, Documentation, Deploy, Incident, Improvement).
  - `CardDependency` (blocks|relates|subtask) e `CardEvent` (append-only) que dirige a automação.
  - Máquina de estados por evento (§16.7) e criação/movimentação/bloqueio de cards.
  - Regras do §16.6 (todo trabalho executável vira card, todo card tem fase, card bloqueado registra motivo).
- Fora de escopo (MVP-1):
  - UI de board (diferida; exposição via API/CLI).
  - Eventos de execução real (PR opened, CI failed) além dos stubs (execução real em MVP-3+); a máquina deve aceitar esses eventos, mas as fontes reais não existem ainda.
  - WIP-limit enforcement rígido (campo existe; enforcement é MVP-2).

## Comportamento esperado

- Ao criar um board para uma orquestração, as 12 colunas são criadas na ordem canônica.
- Cards são criados em `Backlog`/`Ready` e evoluem por eventos registrados como `CardEvent`.
- Transições dirigidas por evento (§16.7), mínimo a suportar:
  - `agent_started` → InProgress
  - `agent_needs_input` → WaitingHuman
  - `pr_opened` → Review
  - `ci_failed` / `gate_failed` → Failed ou Blocked
  - `review_changes_requested` → Review
  - `tests_passed` → Testing (ou Done)
  - `gate_passed` → Done
- Bloquear um card (`block`) exige `reason` e registra `CardEvent`; `unblock` reverte à coluna anterior elegível.
- Todo card carrega `phase`; card sem fase é inválido (§16.6).
- Cada transição gera um `CardEvent` com `from_status`, `to_status`, `actor`, `payload`, `created_at` (rastreabilidade e base da timeline — ver [observability-basic.md](observability-basic.md)).
- Movimentos inválidos (transição não permitida pela máquina) são rejeitados.

## Contratos / Interfaces

Módulo: `src/aso/kanban/`.

```python
# src/aso/kanban/board_service.py
class BoardService:
    async def create_board(self, orchestration_id: UUID, project_id: UUID, scope: BoardScope, name: str) -> Board: ...
    async def get_board(self, board_id: UUID) -> Board: ...
    async def list_cards(self, board_id: UUID) -> list[KanbanCard]: ...

# src/aso/kanban/card_service.py
class CardService:
    async def create_card(self, board_id: UUID, data: CardCreate) -> KanbanCard: ...
    async def move(self, card_id: UUID, to_column: ColumnKey, actor: str) -> KanbanCard: ...
    async def block(self, card_id: UUID, reason: str, actor: str) -> KanbanCard: ...
    async def unblock(self, card_id: UUID, actor: str) -> KanbanCard: ...

# src/aso/kanban/automation.py
class CardStateMachine:
    def apply_event(self, card: KanbanCard, event: CardEventType) -> ColumnKey: ...  # (§16.7)
```

- Endpoints Kanban: `GET/POST /v1/boards`, `GET /v1/boards/{id}`, `GET/POST /v1/boards/{id}/cards`, `PATCH /v1/cards/{id}`, `POST /v1/cards/{id}/move|block|unblock|assign-agent|run` (ver [api-minimal.md](api-minimal.md)).

## Critérios de aceite

- [ ] Board com as 12 colunas e cards são criados corretamente.
- [ ] Card move automaticamente por evento (§16.7) segundo a máquina de estados.
- [ ] Card reflete o estado real (transições geram `CardEvent`; movimentos inválidos são rejeitados).
- [ ] Bloqueio registra motivo obrigatório; card sem fase é inválido.

## Rastreabilidade

§16/§40 Task 4 → ADR-0002 → esta spec → TASK-04 → `src/aso/kanban/` (board_service, card_service, automation), tabelas `boards`, `board_columns`, `kanban_cards`, `card_dependencies`, `card_events` → `tests/unit/test_card_state_machine.py`, `tests/integration/test_kanban.py`
