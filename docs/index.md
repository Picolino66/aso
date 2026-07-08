# ASO Runtime — Documentação

Documentação canônica (fonte de verdade para agentes) do **ASO Runtime — Autonomous Software Orchestrator Runtime**.

Todo conteúdo é mantido em **português do Brasil (pt-BR)**.

## Estado da orquestração

- **Modo:** `full-pipeline` (F1 → F7)
- **Stack:** Python (ver ADR-0004)
- **Fase atual:** **F7 concluída — pipeline F1–F7 fechado** (observabilidade, SLOs, feedback→backlog)
- **Snapshot estável:** O7 (F1–F7 PASSED)
- **Código:** `src/aso/` · 84 testes · cobertura 97% · ruff+mypy OK · API v1 (auth/RBAC) + **console web `/ui`** + CLI · persistência normalizada (Alembic) · CI + smoke Docker · métricas/SLOs + `/metrics` Prometheus
- **Rodar tudo em Docker:** `docker compose up --build` → API em `http://localhost:8000` (UI em `/ui`, docs em `/docs`)

## Índice

### Governança e contexto
- Contexto canônico: [`.aso/context/orchestrator-context.json`](../.aso/context/orchestrator-context.json)
- Snapshots: [`.aso/snapshots/`](../.aso/snapshots/)
- Quality gates: [`.aso/quality-gates/`](../.aso/quality-gates/)

### Fases
- [F1 — Discovery & Strategy](phases/F1-discovery.md) ✅
- [F2 — Architecture & Design](phases/F2-architecture.md) ✅
- [F3 — Data & API Contracts](phases/F3-contracts.md) ✅
- [F4 — UX/UI & Planning](phases/F4-planning.md) ✅
- [F5 — Engineering Execution](phases/F5-execution.md) ✅ *(MVP-1 completo; 15/15 cards)*
- [F6 — Quality, Docs & Deploy](phases/F6-quality.md) ✅ *(CI/CD, segurança, docs, deploy/rollback)*
- [F7 — Operate & Evolve](phases/F7-operate.md) ✅ *(observabilidade, SLOs, feedback→backlog)*

### Documentação técnica
- [Requisitos (resumo)](requirements.md) · [Requisitos completos](../requerimentos.md)
- [Arquitetura](architecture.md) · [Modelo de domínio](domain-model.md) · [API](api.md) · [`contracts/openapi.yaml`](../contracts/openapi.yaml)
- [Kanban](kanban.md) · [Agentes](agents.md) · [Contexto](context.md) · [Quality Gates](quality-gates.md) · [Snapshots](snapshots.md)
- [Operações (runbook)](operations.md) · [Deploy & Rollback](deploy.md) · [CHANGELOG](../CHANGELOG.md)
- [MVP-1](mvp/mvp-1.md)

### Estrutura agentic
- [`specs/`](../specs/README.md) · [`tasks/`](../tasks/README.md) · [`agents/`](../agents/README.md) · [`skills/`](../skills/README.md)

### ADRs
- [ADR-0001 — Arquitetura do runtime (Modular Monolith + Hexagonal)](adrs/ADR-0001-runtime-architecture.md)
- [ADR-0002 — Kanban como plano de execução](adrs/ADR-0002-kanban-as-execution-plane.md)
- [ADR-0003 — ContextBus como governança soberana](adrs/ADR-0003-contextbus-governance.md)
- [ADR-0004 — Stack de implementação: Python](adrs/ADR-0004-tech-stack-python.md)
- [ADR-0005 — Consistência de dados e versionamento de API](adrs/ADR-0005-data-consistency-and-api-versioning.md)
- [ADR-0006 — Persistência: repository ports + adapters (SQLAlchemy)](adrs/ADR-0006-persistence-repository-adapters.md)
