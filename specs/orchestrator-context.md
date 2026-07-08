# SPEC — OrchestratorContext versionado

- **Card:** TASK-03
- **Épico:** EPIC-2 (Domínio & Contexto)
- **Fase:** F5
- **ADRs:** ADR-0003, ADR-0005
- **Requisitos:** §17, §40 Task 3
- **Depende de:** TASK-02

## Objetivo

Implementar o `OrchestratorContext`, o estado canônico versionado de cada orquestração (§17). É a "verdade central soberana" do projeto (§8.3): nenhum agente escreve nele diretamente — apenas o ContextBus (ver [context-patch-contextbus.md](context-patch-contextbus.md)), conforme ADR-0003.

O contexto é persistido como JSONB no Postgres com `version` incremental e histórico append-only, permitindo recuperação por snapshot e auditoria de evolução (ADR-0005 — consistência forte). Esta feature entrega criação, leitura, escrita versionada e cálculo de `context_hash`.

## Escopo

- Incluído:
  - Schema do payload com as seções do §17.1: `product, market, business, requirements, scope, feasibility, architecture, ux, contracts, engineering, agentic, quality, operations, kanban, adrs, snapshots, conflicts, approvals, orchestration, metadata`.
  - Persistência JSONB; cada escrita cria uma nova linha versionada (append-only), preservando o histórico.
  - `version` incremental (inteiro monotônico por orquestração) e `context_hash` (hash determinístico do payload).
  - Serviço de leitura da versão corrente e de recuperação de versão por `version`/snapshot.
  - `agentic` com sub-mapas: `agents_map, skills_map, tools_map, execution_providers, tasks_map`.
- Fora de escopo (MVP-1):
  - Diff visual/estrutural entre versões (MVP-5).
  - Locks finos por `target_keys` e resolução de contenção concorrente (TRISK-02) — mitigação básica só; refinamento em MVP-2.
  - Validação semântica das seções (fica no pipeline do ContextBus).

## Comportamento esperado

- Ao criar uma `Orchestration`, cria-se um `OrchestratorContext` inicial `version=1`, `snapshot_version=O0`, seções vazias e `context_hash` calculado.
- Toda escrita autorizada (feita pelo ContextBus) incrementa `version` e recalcula `context_hash`; a versão anterior permanece recuperável (append-only, §17.2).
- Leitura padrão retorna a versão corrente (maior `version`); leitura histórica aceita `version` explícita.
- `context_hash` é determinístico para o mesmo payload (usado por snapshots — §23 — e detecção de mudança).
- Escrita direta fora do ContextBus não é permitida pela API pública do serviço (invariante de ADR-0003).
- Consistência forte dentro da orquestração: escrita e incremento de versão são atômicos (transação única).

## Contratos / Interfaces

Módulo: `src/aso/governance/context/`.

```python
# src/aso/governance/context/service.py
class OrchestratorContextService:
    async def create(self, orchestration_id: UUID, execution_mode: str) -> OrchestratorContext: ...
    async def get_current(self, orchestration_id: UUID) -> OrchestratorContext: ...
    async def get_version(self, orchestration_id: UUID, version: int) -> OrchestratorContext: ...
    async def history(self, orchestration_id: UUID) -> list[OrchestratorContextMeta]: ...
    # escrita restrita — usada apenas pelo ContextBus
    async def _write_new_version(self, orchestration_id: UUID, payload: dict, actor: str) -> OrchestratorContext: ...

def compute_context_hash(payload: dict) -> str: ...  # hash determinístico (ex.: sha256 de JSON canônico)
```

- Persistência: tabela `orchestrator_contexts` (§29) com coluna `payload JSONB`, `version INT`, `context_hash`, `current_phase`, `snapshot_version`, `created_at`.
- Endpoint de leitura: `GET /v1/orchestrations/{id}/context` (ver [api-minimal.md](api-minimal.md)).

## Critérios de aceite

- [ ] Contexto é criado junto da orquestração e pode ser lido (versão corrente).
- [ ] Cada escrita autorizada incrementa `version` e mantém a versão anterior recuperável (append-only).
- [ ] `context_hash` é recalculado a cada escrita e é determinístico para o mesmo payload.
- [ ] Histórico é recuperável por `version` e utilizável por snapshot.
- [ ] Não há caminho público para escrever no contexto fora do ContextBus.

## Rastreabilidade

§17/§40 Task 3 → ADR-0003, ADR-0005 → esta spec → TASK-03 → `src/aso/governance/context/`, tabela `orchestrator_contexts` → `tests/unit/test_context_versioning.py`, `tests/integration/test_context_persistence.py`
