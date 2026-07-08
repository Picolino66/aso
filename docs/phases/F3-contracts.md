# F3 — Data & API Contracts — ASO Runtime

> Fase F3. Depende de O2 (F2 aprovada). Estado: **F3 concluída — snapshot O3 gerado** (aguardando gate F3→F4).

## 1. Entidades e schemas

Modelo de domínio completo em [domain-model.md](../domain-model.md): agregados por plane, atributos e relacionamentos. Todas as entidades têm `id` (UUID) e timestamps. Sem campos genéricos sem descrição.

## 2. Modelo de consistência

**Forte** (transacional, um PostgreSQL). Ver [ADR-0005](../adrs/ADR-0005-data-consistency-and-api-versioning.md). `OrchestratorContext` versionado com histórico append-only; escrita serializada pelo ContextBus (ADR-0003) com locks por `target_keys`.

## 3. Contratos de API

- Versão base **v1** (prefixo de path).
- Catálogo humano em [api.md](../api.md); spec de máquina em [`contracts/openapi.yaml`](../../contracts/openapi.yaml).
- Erros padronizados (RFC 7807-like); idempotência via `Idempotency-Key`; paginação padrão.

## 4. DTOs principais

`CreateOrchestration`, `Orchestration`, `OrchestratorContext`, `CreateCard`, `KanbanCard`, `ContextPatch`, `Conflict`, `QualityGateResult`, `ADR`, `HumanApproval` — todos tipados no OpenAPI, prontos para materialização em Pydantic v2.

## 5. Idempotência e versionamento

- `Idempotency-Key` em POSTs de criação (orchestrations, cards, adrs, approvals).
- Mudança incompatível de contrato → nova versão `/v2` + atualização de consumidores.
- Migrations com Alembic; nenhuma alteração de schema fora de migration.

## 6. Eventos (visão inicial)

Eventos de domínio para automação do Kanban e observabilidade: `CardMoved`, `AgentRunStarted/Finished`, `ContextPatchApplied`, `QualityGateEvaluated`, `SnapshotCreated`, `ConflictRaised`, `ApprovalRequested`. AsyncAPI detalhado é diferido (sem mensageria no MVP — comunicação in-process).

## 7. Compatibilidade com F2

Persistência (Postgres + JSONB), monolito modular e ContextBus single-writer são coerentes com O2. Nenhuma entidade contradiz `architecture.*`.

## 8. Quality Gate F3 → F4

| Critério | Status | Evidência |
|---|---|---|
| Schema de dados versionado e revisado | ✅ PASSED | domain-model.md + ADR-0005 |
| OpenAPI sem campos obrigatórios ausentes | ✅ PASSED | contracts/openapi.yaml |
| Modelo de consistência com ADR | ✅ PASSED | ADR-0005 (forte) |
| Limites transacionais mapeados | ✅ PASSED | Contexto: escrita via ContextBus; agregados por plane |
| Nenhum campo `any`/`object` sem definição | ✅ PASSED | DTOs descritos; `payload` do contexto referencia §17 |

**Resultado: PASSED → snapshot O3 gerado. Apto a avançar para F4.**
