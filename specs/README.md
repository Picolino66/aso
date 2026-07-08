# SPECS — ASO Runtime (MVP-1)

> Fase **F4 — UX/UI & Planning**. Especificações funcionais de cada feature do MVP-1 (Core de governança), derivadas dos cards `TASK-01..TASK-15` do [board](../.aso/kanban/board.json).
> Cada spec é a fonte de verdade funcional para a implementação em **F5 (Engineering Execution)**.

## Referências-base

- Requisitos: [`requerimentos.md`](../requerimentos.md)
- Domínio: [`docs/domain-model.md`](../docs/domain-model.md)
- API: [`docs/api.md`](../docs/api.md) · contrato de máquina em `contracts/openapi.yaml`
- Arquitetura: [`docs/phases/F2-architecture.md`](../docs/phases/F2-architecture.md)
- ADRs: [`docs/adrs/`](../docs/adrs/)

## Stack (locked — ADR-0004)

Python 3.12+ · FastAPI + Uvicorn · Pydantic v2 · PostgreSQL 16 (JSONB) + SQLAlchemy 2.x + Alembic · Typer · asyncio · pytest · ruff + mypy · Docker Compose.
Padrão: **Modular Monolith + Clean/Hexagonal + DDD** (ADR-0001). Módulos em `src/aso/{control,kanban,agents,execution,governance,observability,shared,api,cli,db}`.

## Índice de specs

| # | Spec | Card | Épico | Prioridade | Depende de |
|---|---|---|---|---|---|
| 1 | [project-setup.md](project-setup.md) — Estrutura base + tooling | TASK-01 | EPIC-1 | critical | — |
| 2 | [domain-models.md](domain-models.md) — Modelos de domínio (Pydantic + tabelas) | TASK-02 | EPIC-2 | critical | TASK-01 |
| 3 | [orchestrator-context.md](orchestrator-context.md) — OrchestratorContext versionado | TASK-03 | EPIC-2 | critical | TASK-02 |
| 4 | [kanban.md](kanban.md) — Kanban básico + automação | TASK-04 | EPIC-3 | high | TASK-02 |
| 5 | [execution-plan.md](execution-plan.md) — ExecutionPlan a partir de solicitação | TASK-05 | EPIC-4 | high | TASK-03 |
| 6 | [multiagent-decision-engine.md](multiagent-decision-engine.md) — MultiAgentDecisionEngine básico | TASK-06 | EPIC-4 | high | TASK-03 |
| 7 | [agent-registry.md](agent-registry.md) — AgentRegistry | TASK-07 | EPIC-5 | high | TASK-02 |
| 8 | [agent-executor-mock.md](agent-executor-mock.md) — AgentExecutor mock | TASK-08 | EPIC-5 | high | TASK-07 |
| 9 | [context-patch-contextbus.md](context-patch-contextbus.md) — ContextPatch + ContextBus | TASK-09 | EPIC-6 | critical | TASK-03 |
| 10 | [adr-registry.md](adr-registry.md) — ADRRegistry | TASK-10 | EPIC-6 | high | TASK-02 |
| 11 | [quality-gate-engine.md](quality-gate-engine.md) — QualityGateEngine básico | TASK-11 | EPIC-6 | critical | TASK-03 |
| 12 | [snapshot-engine.md](snapshot-engine.md) — SnapshotEngine básico | TASK-12 | EPIC-6 | high | TASK-11 |
| 13 | [api-minimal.md](api-minimal.md) — API mínima (FastAPI) | TASK-13 | EPIC-7 | medium | TASK-09, TASK-11, TASK-12 |
| 14 | [cli-minimal.md](cli-minimal.md) — CLI mínima (Typer) | TASK-14 | EPIC-7 | medium | TASK-13 |
| 15 | [observability-basic.md](observability-basic.md) — Observabilidade básica + docs | TASK-15 | EPIC-8 | medium | TASK-13 |

## Ordem sugerida de implementação (grafo de dependências)

```
TASK-01
  └─ TASK-02 ─┬─ TASK-03 ─┬─ TASK-05
              │           ├─ TASK-06
              │           ├─ TASK-09 ─┐
              │           └─ TASK-11 ─┼─ TASK-12
              ├─ TASK-04  │           │
              ├─ TASK-07 ─ TASK-08    │
              └─ TASK-10              │
                                      └─ TASK-13 ─┬─ TASK-14
                                                  └─ TASK-15
```

## Critérios de aceite globais do MVP-1 (§35)

As 15 specs, em conjunto, satisfazem os critérios §35: criar orquestração, gerar ExecutionPlan e OrchestratorContext, criar board/cards, decidir single vs multi-agent, executar agente simulado, produzir ContextPatch, validar/aplicar via ContextBus, registrar ADR, rodar quality gate, gerar snapshot, exibir timeline e Kanban, registrar logs.
