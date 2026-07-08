# tasks/ — Backlog executável (MVP 1)

> Estrutura agentic (F4). Backlog materializado como cards em [`.aso/kanban/board.json`](../.aso/kanban/board.json). Rastreabilidade: requisito → ADR → spec → task → código → teste → gate → snapshot.

## Ordem de execução (respeita dependências)

```
TASK-01 (fundação)
  └─ TASK-02 (domínio) ─┬─ TASK-03 (contexto) ─┬─ TASK-05 (execution plan)
                        │                       ├─ TASK-06 (decision engine)
                        │                       ├─ TASK-09 (contextbus) ── TASK-13 (API) ── TASK-14 (CLI)
                        │                       ├─ TASK-11 (quality gate) ── TASK-12 (snapshot)
                        │                       └─ ...
                        ├─ TASK-04 (kanban)
                        ├─ TASK-07 (agent registry) ── TASK-08 (executor mock)
                        └─ TASK-10 (adr registry)
                                                        TASK-15 (observabilidade+docs) depende de TASK-13
```

## Tasks

| Task | Épico | Spec | Depende de | Prioridade |
|---|---|---|---|---|
| TASK-01 Estrutura base + tooling | EPIC-1 | project-setup | — | critical |
| TASK-02 Modelos de domínio | EPIC-2 | domain-models | TASK-01 | critical |
| TASK-03 OrchestratorContext versionado | EPIC-2 | orchestrator-context | TASK-02 | critical |
| TASK-04 Kanban básico + automação | EPIC-3 | kanban | TASK-02 | high |
| TASK-05 ExecutionPlan | EPIC-4 | execution-plan | TASK-03 | high |
| TASK-06 MultiAgentDecisionEngine | EPIC-4 | multiagent-decision-engine | TASK-03 | high |
| TASK-07 AgentRegistry | EPIC-5 | agent-registry | TASK-02 | high |
| TASK-08 AgentExecutor mock | EPIC-5 | agent-executor-mock | TASK-07 | high |
| TASK-09 ContextPatch + ContextBus | EPIC-6 | context-patch-contextbus | TASK-03 | critical |
| TASK-10 ADRRegistry | EPIC-6 | adr-registry | TASK-02 | high |
| TASK-11 QualityGateEngine | EPIC-6 | quality-gate-engine | TASK-03 | critical |
| TASK-12 SnapshotEngine | EPIC-6 | snapshot-engine | TASK-11 | high |
| TASK-13 API mínima | EPIC-7 | api-minimal | TASK-09,11,12 | medium |
| TASK-14 CLI mínima | EPIC-7 | cli-minimal | TASK-13 | medium |
| TASK-15 Observabilidade + docs | EPIC-8 | observability-basic | TASK-13 | medium |

Critérios de aceite por card em `.aso/kanban/board.json`. Definition of Done global em §42 do requisito.
