# F4 — UX/UI & Planning — ASO Runtime

> Fase F4. Depende de O3. Estado: **F4 concluída — snapshot O4 gerado** (aguardando gate F4→F5).

## 1. Jornadas críticas (ASO é ferramenta de engenharia; UI web diferida, foco API/CLI)

| Jornada | Persona | Fluxo | Validação |
|---|---|---|---|
| J1 — Criar orquestração | Tech Lead | `aso run "..."` / `POST /v1/orchestrations` → ExecutionPlan + contexto + board | Board e cards criados automaticamente |
| J2 — Acompanhar execução | Eng. Manager | `aso board <id>` / `GET .../timeline` → colunas, cards, agentes, gates | Timeline reflete estado real |
| J3 — Aprovar ação crítica | Arquiteto | `HumanApproval` pendente → `aso approve <id>` | Ação só executa após aprovação |
| J4 — Revisar decisão | Arquiteto | `aso adrs list` / `GET .../adrs` → ADRs e trade-offs | ADR rastreável a card/requisito |
| J5 — Rollback de fase | Arquiteto | `aso rollback <id> --to O3` | Contexto restaurado + ADR de rollback |

Jornadas validadas conceitualmente (sem UI complexa no MVP — §7). `usability-testing-engine`: fluxos CLI/API objetivos, baixo atrito.

## 2. Module map (sem dependências circulares)

```
shared        (tipos, schemas, eventos, utils)         — sem dependências
  ▲
governance ── kanban ── observability                  — dependem de shared
  ▲             ▲
agents (depende de shared + lê contexto via governance)
  ▲
execution (depende de shared + agents)
  ▲
control (orquestra: depende de governance, kanban, agents, execution, observability)
  ▲
api · cli (driving adapters: dependem de control + casos de uso)
```

Regra de dependência aponta para dentro (Clean Architecture). Verificável por lint de imports. **Nenhum ciclo.**

## 3. Estrutura agentic (criada/validada)

| Diretório | Conteúdo |
|---|---|
| `docs/` | Documentação canônica (fonte de verdade) — índice, fases, domínio, api, kanban, agents, gates, snapshots |
| `docs/adrs/` | ADRs (ADR-0001..0005) |
| `specs/` | Specs por feature planejada (MVP-1) — ver [`specs/README.md`](../../specs/README.md) |
| `tasks/` | Decomposição de tarefas / backlog executável — ver [`tasks/README.md`](../../tasks/README.md) |
| `agents/` | Mapa de agentes e ownership — ver [`agents/README.md`](../../agents/README.md) |
| `skills/` | Mapa de skills reutilizáveis — ver [`skills/README.md`](../../skills/README.md) |
| `.aso/` | Estado do runtime: contexto, snapshots, gates, kanban |

## 4. Convenção de rastreabilidade

`requisito (requerimentos.md §X) → ADR (ADR-XXXX) → spec (specs/<feature>.md) → task/card (TASK-XX / board.json) → implementação (src/aso/...) → teste (tests/...) → gate (Fx) → snapshot (Ox)`

- Todo card referencia: `linked_requirements`, `linked_adrs`, `linked_contracts`, spec de origem.
- Toda spec referencia o requisito e os ADRs que a sustentam.
- Todo teste referencia a task/critério de aceite que valida.

## 5. Backlog (MVP-1 — Core de governança)

Épicos e tasks materializados como cards em [`.aso/kanban/board.json`](../../.aso/kanban/board.json) e detalhados em [`tasks/README.md`](../../tasks/README.md).

| Épico | Tasks | Prioridade |
|---|---|---|
| EPIC-1 Fundação do projeto | TASK-01 estrutura base + tooling | critical |
| EPIC-2 Domínio & Contexto | TASK-02 modelos de domínio · TASK-03 OrchestratorContext versionado | critical |
| EPIC-3 Kanban básico | TASK-04 board/colunas/cards + automação | high |
| EPIC-4 Planejamento & Decisão | TASK-05 ExecutionPlan · TASK-06 MultiAgentDecisionEngine | high |
| EPIC-5 Agentes | TASK-07 AgentRegistry · TASK-08 AgentExecutor mock | high |
| EPIC-6 Governança | TASK-09 ContextPatch+ContextBus · TASK-10 ADRRegistry · TASK-11 QualityGateEngine · TASK-12 SnapshotEngine | critical |
| EPIC-7 Interfaces | TASK-13 API mínima · TASK-14 CLI mínima | medium |
| EPIC-8 Observabilidade & Docs | TASK-15 logs/timeline + docs | medium |

## 6. Priorização (valor × risco × esforço)

1. EPIC-1, EPIC-2, EPIC-6 (fundação + governança — maior valor e risco; habilitam o resto)
2. EPIC-3, EPIC-4, EPIC-5 (fluxo operacional)
3. EPIC-7, EPIC-8 (superfície e observabilidade)

Ordem respeita dependências: contexto/domínio antes de governança; governança antes de agentes; tudo antes de API/CLI.

## 7. Threshold de cobertura

`test_coverage_threshold = 80%` (core: MultiAgentDecisionEngine, ContextBus, ContextPatchValidator, QualityGateEngine, SnapshotEngine, ADRRegistry, KanbanCardService — §41). Aplicado como gate em F5/F6.

## 8. Quality Gate F4 → F5

| Critério | Status | Evidência |
|---|---|---|
| Jornadas críticas validadas | ✅ PASSED | Seção 1 (J1–J5) |
| Backlog com ≥1 sprint | ✅ PASSED | 8 épicos / 15 tasks (board.json, tasks/) |
| Histórias com critérios de aceite verificáveis | ✅ PASSED | tasks/README.md + board.json |
| Módulos sem dependências circulares | ✅ PASSED | Seção 2 |
| Estrutura agentic criada/validada | ✅ PASSED | Seção 3 (docs/specs/tasks/agents/skills) |
| Specs para todas as features antes de tasks | ✅ PASSED | specs/ |
| Convenção de rastreabilidade definida | ✅ PASSED | Seção 4 |
| Mapa de agentes/skills com ownership | ✅ PASSED | agents/README.md · skills/README.md |
| Threshold de cobertura registrado | ✅ PASSED | Seção 7 (80%) |

**Resultado: PASSED → snapshot O4 gerado. Apto a avançar para F5 (Engineering Execution) mediante aprovação.**
