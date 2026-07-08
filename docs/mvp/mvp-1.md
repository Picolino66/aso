# MVP-1 — Core de governança

> Escopo, entregáveis, critérios de aceite e backlog do MVP-1.
> Requisito: [`requerimentos.md` §35–§36](../../requerimentos.md). Planejamento: [F4 — UX/UI & Planning](../phases/F4-planning.md).

## 1. Objetivo

Entregar o **core de governança** do ASO Runtime: uma orquestração capaz de gerar `ExecutionPlan` + `OrchestratorContext` versionado + Kanban board, decidir single vs multi-agent, executar ao menos um agente (mock), produzir `ContextPatch` validado pelo `ContextBus`, registrar ADR, rodar um quality gate, gerar snapshot e exibir a timeline.

> **O MVP-1 NÃO executa código real ainda (§36).** A execução real de código e a integração com CLI agents evoluem nos MVPs 3–4. Neste estágio usa-se `ExecutionProvider` abstrato com **provider local/mock**.

## 2. Entregáveis (§36)

`OrchestratorRuntime` · `OrchestratorContext` · `ExecutionPlan` · Kanban básico · `AgentRegistry` · `MultiAgentDecisionEngine` básico · `ContextPatch` · `ContextBus` · `ADRRegistry` · `QualityGateEngine` básico · `SnapshotEngine` básico · logs básicos · API funcional e/ou UI simples (o MVP-1 entrega **API + CLI**; UI web diferida).

## 3. Critérios de aceite (§35)

O MVP-1 será aceito quando o sistema conseguir:

1. Criar uma orquestração.
2. Gerar um `ExecutionPlan`.
3. Criar um `OrchestratorContext`.
4. Criar um Kanban board para a orquestração.
5. Criar cards automaticamente.
6. Decidir entre single-agent e multi-agent.
7. Executar pelo menos um agente simulado ou real.
8. O agente produzir um `ContextPatch`.
9. O `ContextBus` validar e aplicar o patch.
10. Registrar uma ADR.
11. Rodar um quality gate simples.
12. Gerar um snapshot.
13. Exibir a timeline da orquestração.
14. Exibir o Kanban.
15. Registrar logs básicos.

## 4. Backlog (épicos e tasks)

Materializado como cards em [`.aso/kanban/board.json`](../../.aso/kanban/board.json) e detalhado em [`tasks/README.md`](../../tasks/README.md). O Kanban é o **plano de execução** (ADR-0002), não apenas visual.

| Épico | Tasks | Prioridade |
|---|---|---|
| EPIC-1 Fundação do projeto | TASK-01 estrutura base + tooling | critical |
| EPIC-2 Domínio & Contexto | TASK-02 modelos de domínio · TASK-03 OrchestratorContext versionado | critical |
| EPIC-3 Kanban básico | TASK-04 board/colunas/cards + automação | high |
| EPIC-4 Planejamento & Decisão | TASK-05 ExecutionPlan · TASK-06 MultiAgentDecisionEngine | high |
| EPIC-5 Agentes | TASK-07 AgentRegistry · TASK-08 AgentExecutor mock | high |
| EPIC-6 Governança | TASK-09 ContextPatch+ContextBus · TASK-10 ADRRegistry · TASK-11 QualityGateEngine · TASK-12 SnapshotEngine | critical |
| EPIC-7 Interfaces (API/CLI) | TASK-13 API mínima · TASK-14 CLI mínima | medium |
| EPIC-8 Observabilidade & Docs | TASK-15 logs/timeline + docs | medium |

**Ordem** (respeita dependências): domínio/contexto → governança → agentes → API/CLI. Prioridade: EPIC-1/2/6 primeiro (fundação + governança), depois EPIC-3/4/5 (fluxo operacional), por fim EPIC-7/8. Ver [F4 §5–§6](../phases/F4-planning.md).

## 5. Qualidade

`test_coverage_threshold = 80%` no core (MultiAgentDecisionEngine, ContextBus, ContextPatchValidator, QualityGateEngine, SnapshotEngine, ADRRegistry, KanbanCardService — §41), aplicado como gate em F5/F6.

## 6. Roadmap além do MVP-1 (§36)

MVP-2 Multiagente real · MVP-3 Execution Plane (worktrees, terminal, git, testes, lint, build, PR) · MVP-4 Provider inspirado no AgentWrapper · MVP-5 Produto completo (F1–F7, UI completa, operação F7).

## Referências

- Requisitos: [`requerimentos.md` §35–§36](../../requerimentos.md)
- Backlog: [`tasks/README.md`](../../tasks/README.md) · [`.aso/kanban/board.json`](../../.aso/kanban/board.json)
- Planejamento: [F4 — UX/UI & Planning](../phases/F4-planning.md)
- Índice: [`docs/index.md`](../index.md)
