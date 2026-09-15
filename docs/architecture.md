# Arquitetura — ASO Runtime

> Resumo da arquitetura. **Fonte completa:** [F2 — Architecture & Design](phases/F2-architecture.md).
> Decisões: [ADR-0001 — Arquitetura do runtime](adrs/ADR-0001-runtime-architecture.md) · [ADR-0004 — Stack Python](adrs/ADR-0004-tech-stack-python.md).

## 1. Padrão arquitetural

**Modular Monolith + Clean/Hexagonal (Ports & Adapters) + DDD.** Os 6 *planes* do §10 do requisito são mapeados como **bounded contexts (módulos de domínio)** dentro de um único deployable. O módulo `governance` é o núcleo soberano: nenhum outro módulo escreve no contexto sem passar pelo `ContextBus`. Ver [ADR-0001](adrs/ADR-0001-runtime-architecture.md).

| Plane (§10) | Módulo | Responsabilidade (resumo) |
|---|---|---|
| Control | `control` | `OrchestrationService` (serviço de aplicação que concentra fases, aprovações, gates e execução), `MultiAgentDecisionEngine`, `ExecutionPlanner`, `PlanningService`, triagem/discovery/spec/revisão, `next_step` |
| Kanban | `kanban` | `BoardService`, `KanbanCard`, transições manuais validadas, hierarquia, eventos de card |
| Agent | `agents` | `AgentRegistry`, `AgentSupervisor` (uma tentativa; retry pelo roteamento de falha, ADR-0071), `PromptBuilder`, `ContextBuilder`, contrato `TaskEnvelope` |
| Execution | `execution` | `ExecutionProvider` (mock, LLM, CLI, roteamento), `WorktreeManager`, `CandidateRunner`, catálogo de executores, workspace/docs-first |
| Governance | `governance` | `OrchestratorContextStore`, `ContextBus`, `ConflictDetector`, `QualityGateEngine` + definições por fase, `ADRRegistry`, `SnapshotEngine` |
| Observability | `observability` | logging estruturado (structlog), `EventBroker` (SSE), métricas/SLO, rate limit, tracing opcional, log de agentes, aprendizado |

> **Camada de aplicação (ADR-0066, MEL-32):** toda a lógica do antigo `OrchestrationService`
> (7.834 linhas) está em `src/aso/application/`, um serviço por caso de uso:
> `bundles.py` (`BundleStore` — cache, hidratação, persistência e **lock por orquestração, fonte
> única**), `queries.py` (leituras), `intake.py` (criação, triagem, planejamento),
> `classificacao.py` (reclassificação, replanejamento, duplicação), `preparation.py` (discovery,
> especificação, documentos), `settings.py` (executor/esforço efetivos, atribuições, validações,
> orçamento, worktrees), `agent_task.py` (tarefa do agente e `AgentRun`), `execution.py` (claim,
> execução, falhas, freios), `candidates.py` (corrida), `cards.py` (operações do board),
> `delivery.py` (PR, CI, revisão, merge), `docs_first.py` (análise e self-heal de docs),
> `workflow.py` (fases, gate, autopilot — único lugar que muda fase), `recovery.py` (retry),
> `approvals.py` (aprovações, kill-switch, restauração), `qa.py`, `release.py`, `governanca.py`
> (patches, conflitos, auditoria, SLO), `insights.py` (aprendizado e próximo passo) e
> `catalogs.py` (projetos, executores, regras, agentes). `composicao.py` é a raiz de composição;
> `application/orchestration_service.py` virou façade declarativa (`delegacao.py::Delegado`, tipada
> pela assinatura do serviço). Na API, `app.py` só compõe o gateway (auth, rate limit, tracing,
> log) e os routers de `api/routers/` (um por recurso, com `api/deps.py` e `api/schemas.py`).

> Componentes citados em versões anteriores deste documento **não existem** no código:
> `OrchestratorRuntime`, `PhaseController`, `AgentRouter`, `DependencyGraph`,
> `HumanApprovalEngine`, `TerminalRuntime`, `AuditLog` (como componente), `ToolPermissionEngine`,
> `CostTracker`, `TokenUsageTracker`, `AgentRunTimeline`. Aprovações vivem em
> `OrchestrationService` (`HumanApproval`); a trilha de auditoria é o `EventLog` + patches do
> bus; custo vem do envelope do agente (ADR-0026).

## 2. Mapa de camadas e módulos

Regra de dependência aponta para dentro (Clean Architecture) e é **verificada**: contrato de
camadas do `import-linter` em `pyproject.toml` (`lint-imports`, passo do CI) e
`tests/unit/test_regra_de_dependencia.py` (sem ciclos entre pacotes; `module_map` do
orchestrator-context igual ao grafo real). A façade `OrchestrationService` fica em
`application/`; `observability` lê métricas por uma porta (`FonteDeMetricas`), sem importar a
aplicação (MEL-36).

```
driving adapters:   api (FastAPI)   |   cli (Typer)
                          │
application:        casos de uso por plane (orquestrar, criar card, rotear agente, aplicar patch, rodar gate…)
                          │
domain:             control · kanban · agents · execution · governance · observability
                          │
driven adapters:    db (SQLAlchemy/Postgres) · llm_providers (httpx) · cli_agents (subprocess/pty) · git (worktrees)
```

Camadas verificadas (de cima para baixo; cada uma só importa as de baixo, `|` = independentes):

```
api | cli
bootstrap
db
application            (façade OrchestrationService + serviços por caso de uso)
persistence            (portas, estado serializável, adapters em memória)
control                (modelos de domínio, motor de decisão, triagem, spec, revisão, discovery)
execution
agents | observability
governance | kanban
shared
```

## 3. Stack (locked — ADR-0004)

Python 3.12+ · FastAPI + Uvicorn · Pydantic v2 · PostgreSQL 16 (JSONB) + SQLAlchemy 2.x + Alembic · `httpx` (clientes LLM, `LlmClient`) · `subprocess` (agentes CLI) · git via subprocess (`WorktreeManager`) · Typer (CLI) · pytest + coverage · ruff + mypy · `pyproject.toml` (src layout) · Docker Compose (Postgres). Há **console web** servido pela própria API em `/ui` (páginas estáticas em `src/aso/api/static/`). Ver [ADR-0004](adrs/ADR-0004-tech-stack-python.md) (supera a stack TS sugerida no §37 do requisito).

Executores Codex gerenciados são adapters descobertos pelo App Server (`model/list`),
conforme ADR-0011. O domínio não depende do protocolo do fornecedor: o catálogo recebe
capacidades normalizadas e bloqueia incompatibilidades antes de criar worktrees.

## 4. Persistência, segurança e infra (resumo)

- **Dados:** `OrchestratorContext` e snapshots em **JSONB** (escrita atômica, histórico append-only, consistência **forte** por orquestração); entidades operacionais em tabelas relacionais. Detalhe em [F3 — Contracts](phases/F3-contracts.md) e [`domain-model.md`](domain-model.md).
- **Gravação:** incremental por unidade (entidade → `UPDATE`, grupo de junção → reescrita só do dono, `events`/`context_history` → só a cauda) com **versão otimista** em `orchestrations.versao` (conflito → 409); cache LRU de agregados com sonda de versão; schema só por Alembic (ADR-0068).
- **Catálogo multi-repo:** `Project` usa porta própria com adapters in-memory e SQLAlchemy;
  tabelas `projects`/`project_events` e FKs restritivas separam metadados de catálogo do
  agregado da orquestração. Arquivamento preserva rastreabilidade (ADR-0010).
- **Segurança:** secrets env-only (chave nunca exibida por inteiro); RBAC por papel com ações críticas e comandos no host só para `admin` (ADR-0057); aprovações humanas (`HumanApproval`) para estratégia crítica, patches e fases; worktree isolado por agente que altera código; I/O validado por Pydantic; trilha append-only no `EventLog`. Não há permissão de ferramenta por papel (campos informativos no catálogo, ADR-0075). Mapa regra → teste: [`GOVERNANCE.md`](GOVERNANCE.md).
- **Infra:** local-first, **processo único**; handlers FastAPI síncronos no threadpool do Starlette; com `ASO_EXECUCAO_ASSINCRONA=1` as rotas que acionam agentes enfileiram jobs (tabela `jobs`) consumidos por `ASO_WORKERS` threads do mesmo processo (ADR-0067); Docker Compose para Postgres; escala vertical primeiro (múltiplas réplicas: MEL-56).

## Referências

- Arquitetura completa: [F2 — Architecture & Design](phases/F2-architecture.md)
- Governança de contexto: [`context.md`](context.md)
- ADRs: [ADR-0001](adrs/ADR-0001-runtime-architecture.md) · [ADR-0003](adrs/ADR-0003-contextbus-governance.md) · [ADR-0004](adrs/ADR-0004-tech-stack-python.md) · [ADR-0005](adrs/ADR-0005-data-consistency-and-api-versioning.md) · [ADR-0010](adrs/ADR-0010-catalogo-multi-repo-governado.md)
