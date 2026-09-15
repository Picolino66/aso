# Contexto e Governança — ASO Runtime

> Explica o `OrchestratorContext` (§17), o protocolo `ContextPatch` → `ContextBus` (ADR-0003) e o versionamento do estado.
> **Estado canônico vive em:** [`.aso/context/orchestrator-context.json`](../.aso/context/orchestrator-context.json).
> Requisito: [`requerimentos.md` §17–§19](../requerimentos.md). Decisão: [ADR-0003 — ContextBus como governança soberana](adrs/ADR-0003-contextbus-governance.md).

## 1. OrchestratorContext (§17)

Contexto canônico único, **versionado e recuperável por snapshot**, que carrega todo o estado da orquestração e é entregue atualizado a cada agente. É a fonte de verdade do runtime.

Campos de controle: `orchestration_id`, `project_id`, `current_phase` (F1–F7), `snapshot_version` (O0–O7), `execution_mode`.

### Seções canônicas

`product` · `market` · `business` · `requirements` · `scope` · `feasibility` · `architecture` · `contracts` · `ux` · `engineering` · `quality` · `operations` · `kanban` · `agentic` (agents_map, skills_map, tools_map, execution_providers, tasks_map) · `adrs` · `snapshots` · `conflicts` · `approvals` · `metadata`.

Cada fase preenche/consolida suas seções; ao aprovar o gate, as seções correspondentes são congeladas por um snapshot — mapa por fase e regra de override (ADR + aprovação humana) em [`snapshots.md`](snapshots.md) (ADR-0061).

## 2. Regras do contexto (§17.2)

> **Como o agente recebe o contexto (ADR-0063):** o `ContextBuilder`
> (`src/aso/agents/context_builder.py`) monta, por tarefa, um contexto priorizado — card →
> item de spec de origem → discovery aprovado → ficha da demanda → ADRs aceitas relacionadas
> → saídas anteriores das seções `architecture`/`contracts`/`engineering` — dentro de um
> orçamento de caracteres (`ASO_CONTEXTO_MAX_CHARS`, padrão 12.000). Item que não cabe é
> omitido inteiro (com os de menor prioridade) e listado em `omitidos`; o evento
> `AgentExecuted` registra `contexto_chars` e `contexto_omitidos`. O contexto vai no
> `TaskEnvelope` e é renderizado igual para LLM e para o wrapper CLI. A saída de cada card é
> gravada em `<seção>.<card_id>`.

- Todo agente recebe o contexto atualizado.
- **Nenhum agente altera o contexto diretamente.**
- Toda alteração é um `ContextPatch`.
- Todo patch passa por validação.
- O contexto mantém histórico (append-only) e é recuperável por snapshot.

## 3. Protocolo ContextPatch → ContextBus (ADR-0003)

Todo output relevante de agente/skill vira um `ContextPatch` (§18): `patch_type` (`add`/`update`/`propose`/`remove`), `target_path`, `content`, `evidence`, `risks`, `requires_adr`, `requires_approval`.

O `ContextBus` é o **único componente que aplica patches** (single-writer). Antes de aplicar, `ContextBus._validate` roda **8 funções de etapa**, em ordem — **6 com efeito** e 2 ganchos ainda vazios (retornam sempre "ok"):

1. schema (conteúdo obrigatório para add/update/propose)
2. permissão (`PermissionPolicy`, deny-by-default)
3. detecção de conflito entre outputs — **gancho sem efeito** (`_step_conflict_detection`)
4. lock de snapshot (seção congelada exige ADR de override + aprovação humana, ADR-0061)
5. consistência de ADR (`requires_adr` exige `linked_adrs` aceitas)
6. contradição com ADR (`locked_paths` exigem referenciar a ADR)
7. compatibilidade de contrato (`contracts.api_version` imutável, sem remoção in-place)
8. impacto em quality gate — **gancho sem efeito** (`_step_quality_gate_impact`)

**Se aprovado:** aplica o patch, incrementa a versão e registra evento; patch `propose` ou `requires_approval` fica **pendente** e gera `HumanApproval tipo=patch`.
**Se reprovado:** registra um `Conflict`; quando o patch veio da execução de um card, o card vai para `Blocked` ("conflito detectado"). A "resolução" cria um card `ADRTask` atribuído ao `ConflictResolutionAgent` com uma sugestão fixa por tipo de conflito — não há agente de resolução automática.

Concorrência: `threading.RLock` **por orquestração** (`OrchestrationService._lock_for`) — não há locks por chave nem asyncio; não há `Idempotency-Key`. Consistência **forte** por orquestração dentro de um único processo (ver [ADR-0005](adrs/ADR-0005-data-consistency-and-api-versioning.md); múltiplos processos: MEL-56).

## 4. Versionamento e persistência

- A versão do contexto **incrementa a cada escrita** aprovada; histórico append-only.
- Persistência em **JSONB** no PostgreSQL (ver [`architecture.md`](architecture.md) e [F3](phases/F3-contracts.md)).
- Estado materializado do runtime: [`.aso/context/orchestrator-context.json`](../.aso/context/orchestrator-context.json).

## Referências

- Requisitos: [`requerimentos.md` §17–§20](../requerimentos.md)
- Quality gates: [`quality-gates.md`](quality-gates.md) · Snapshots: [`snapshots.md`](snapshots.md)
- ADR: [ADR-0003](adrs/ADR-0003-contextbus-governance.md) · [ADR-0005](adrs/ADR-0005-data-consistency-and-api-versioning.md)
