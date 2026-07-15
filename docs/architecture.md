# Arquitetura — ASO Runtime

> Resumo da arquitetura. **Fonte completa:** [F2 — Architecture & Design](phases/F2-architecture.md).
> Decisões: [ADR-0001 — Arquitetura do runtime](adrs/ADR-0001-runtime-architecture.md) · [ADR-0004 — Stack Python](adrs/ADR-0004-tech-stack-python.md).

## 1. Padrão arquitetural

**Modular Monolith + Clean/Hexagonal (Ports & Adapters) + DDD.** Os 6 *planes* do §10 do requisito são mapeados como **bounded contexts (módulos de domínio)** dentro de um único deployable. O módulo `governance` é o núcleo soberano: nenhum outro módulo escreve no contexto sem passar pelo `ContextBus`. Ver [ADR-0001](adrs/ADR-0001-runtime-architecture.md).

| Plane (§10) | Módulo | Responsabilidade (resumo) |
|---|---|---|
| Control | `control` | OrchestratorRuntime, PhaseController, MultiAgentDecisionEngine, AgentSupervisor, AgentRouter, ExecutionPlanner, DependencyGraph, HumanApprovalEngine |
| Kanban | `kanban` | Board, Card, Swimlane, dependências, assignment, eventos de card |
| Agent | `agents` | AgentRegistry, AgentSupervisor, AgentExecutor, AgentAdapterRegistry, Skill/Tool permissions |
| Execution | `execution` | ExecutionProvider (Local/Mock, Cli, AgentWrapper), WorktreeManager, TerminalRuntime, observers |
| Governance | `governance` | OrchestratorContext, ContextBus, ContextPatchValidator, ConflictDetector, QualityGateEngine, ADRRegistry, SnapshotEngine, ContractValidator |
| Observability | `observability` | TraceService, EventLog, CostTracker, TokenUsageTracker, AgentRunTimeline, AuditLog |

## 2. Mapa de camadas e módulos

Regra de dependência aponta para dentro (Clean Architecture); verificável por lint de imports; **sem ciclos**.

```
driving adapters:   api (FastAPI)   |   cli (Typer)
                          │
application:        casos de uso por plane (orquestrar, criar card, rotear agente, aplicar patch, rodar gate…)
                          │
domain:             control · kanban · agents · execution · governance · observability
                          │
driven adapters:    db (SQLAlchemy/Postgres) · llm_providers (httpx) · cli_agents (subprocess/pty) · git (worktrees)
```

Dependências entre módulos (ver [F4 §2](phases/F4-planning.md)):

```
shared  ◄─ governance ◄─ kanban ◄─ observability
                  ▲          ▲
                agents ◄── execution
                  ▲
                control ◄── api · cli
```

## 3. Stack (locked — ADR-0004)

Python 3.12+ · FastAPI + Uvicorn · Pydantic v2 · PostgreSQL 16 (JSONB) + SQLAlchemy 2.x + Alembic · asyncio · `httpx`/SDK Anthropic (abstração `LLMProvider`) · `subprocess`/PTY (`AgentAdapter`) · git via subprocess (`WorktreeManager`) · Typer (CLI) · pytest + coverage · ruff + mypy · `pyproject.toml` (src layout) · Docker Compose (Postgres). UI web **diferida**: MVP 1 entrega API + CLI. Ver [ADR-0004](adrs/ADR-0004-tech-stack-python.md) (supera a stack TS sugerida no §37 do requisito).

## 4. Persistência, segurança e infra (resumo)

- **Dados:** `OrchestratorContext` e snapshots em **JSONB** (escrita atômica, histórico append-only, consistência **forte** por orquestração); entidades operacionais em tabelas relacionais. Detalhe em [F3 — Contracts](phases/F3-contracts.md) e [`domain-model.md`](domain-model.md).
- **Catálogo multi-repo:** `Project` usa porta própria com adapters in-memory e SQLAlchemy;
  tabelas `projects`/`project_events` e FKs restritivas separam metadados de catálogo do
  agregado da orquestração. Arquivamento preserva rastreabilidade (ADR-0010).
- **Segurança:** secrets env-only (chave nunca exibida por inteiro); `ToolPermissionEngine` com allowlist por papel; `HumanApprovalEngine` obrigatório para ações críticas; worktree isolado por agente que altera código; I/O validado por Pydantic; `AuditLog` append-only.
- **Infra:** local-first, processo único (API + workers asyncio); Docker Compose para Postgres; escala vertical primeiro; sem execução remota distribuída no MVP.

## Referências

- Arquitetura completa: [F2 — Architecture & Design](phases/F2-architecture.md)
- Governança de contexto: [`context.md`](context.md)
- ADRs: [ADR-0001](adrs/ADR-0001-runtime-architecture.md) · [ADR-0003](adrs/ADR-0003-contextbus-governance.md) · [ADR-0004](adrs/ADR-0004-tech-stack-python.md) · [ADR-0005](adrs/ADR-0005-data-consistency-and-api-versioning.md) · [ADR-0010](adrs/ADR-0010-catalogo-multi-repo-governado.md)
