# Contexto e Governança — ASO Runtime

> Explica o `OrchestratorContext` (§17), o protocolo `ContextPatch` → `ContextBus` (ADR-0003) e o versionamento do estado.
> **Estado canônico vive em:** [`.aso/context/orchestrator-context.json`](../.aso/context/orchestrator-context.json).
> Requisito: [`requerimentos.md` §17–§19](../requerimentos.md). Decisão: [ADR-0003 — ContextBus como governança soberana](adrs/ADR-0003-contextbus-governance.md).

## 1. OrchestratorContext (§17)

Contexto canônico único, **versionado e recuperável por snapshot**, que carrega todo o estado da orquestração e é entregue atualizado a cada agente. É a fonte de verdade do runtime.

Campos de controle: `orchestration_id`, `project_id`, `current_phase` (F1–F7), `snapshot_version` (O0–O7), `execution_mode`.

### Seções canônicas

`product` · `market` · `business` · `requirements` · `scope` · `feasibility` · `architecture` · `contracts` · `ux` · `engineering` · `quality` · `operations` · `kanban` · `agentic` (agents_map, skills_map, tools_map, execution_providers, tasks_map) · `adrs` · `snapshots` · `conflicts` · `approvals` · `metadata`.

Cada fase preenche/consolida suas seções; ao aprovar o gate, as seções correspondentes são congeladas por um snapshot (ver [`snapshots.md`](snapshots.md)).

## 2. Regras do contexto (§17.2)

- Todo agente recebe o contexto atualizado.
- **Nenhum agente altera o contexto diretamente.**
- Toda alteração é um `ContextPatch`.
- Todo patch passa por validação.
- O contexto mantém histórico (append-only) e é recuperável por snapshot.

## 3. Protocolo ContextPatch → ContextBus (ADR-0003)

Todo output relevante de agente/skill vira um `ContextPatch` (§18): `patch_type` (`add`/`update`/`propose`/`remove`), `target_path`, `content`, `evidence`, `risks`, `requires_adr`, `requires_approval`.

O `ContextBus` é o **único componente que aplica patches** (single-writer). Antes de aplicar, executa a validação em **7 etapas** (§19):

1. schema validation
2. permission check
3. conflict detection
4. snapshot lock validation
5. ADR consistency validation
6. contract compatibility validation
7. quality gate impact check

**Se aprovado:** aplica o patch, incrementa a versão, registra evento, persiste histórico e atualiza cards relacionados.
**Se reprovado:** registra conflito, move o card para `Blocked`/`WaitingHuman` e aciona o `ConflictResolutionAgent` quando necessário.

Escrita serializada com **locks por `target_keys`** (concorrência asyncio); idempotência via `Idempotency-Key`. Consistência **forte** por orquestração (ver [ADR-0005](adrs/ADR-0005-data-consistency-and-api-versioning.md)).

## 4. Versionamento e persistência

- A versão do contexto **incrementa a cada escrita** aprovada; histórico append-only.
- Persistência em **JSONB** no PostgreSQL (ver [`architecture.md`](architecture.md) e [F3](phases/F3-contracts.md)).
- Estado materializado do runtime: [`.aso/context/orchestrator-context.json`](../.aso/context/orchestrator-context.json).

## Referências

- Requisitos: [`requerimentos.md` §17–§20](../requerimentos.md)
- Quality gates: [`quality-gates.md`](quality-gates.md) · Snapshots: [`snapshots.md`](snapshots.md)
- ADR: [ADR-0003](adrs/ADR-0003-contextbus-governance.md) · [ADR-0005](adrs/ADR-0005-data-consistency-and-api-versioning.md)
