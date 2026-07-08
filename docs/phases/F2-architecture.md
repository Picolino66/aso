# F2 — Architecture & Design — ASO Runtime

> Documento canônico da fase F2. Depende de O1 (F1 aprovada).
> Estado: **F2 concluída — snapshot O2 gerado** (aguardando aprovação do gate F2→F3).

## 1. Padrão arquitetural

**Modular Monolith + Clean/Hexagonal Architecture (Ports & Adapters) + DDD.**

Os 6 *planes* do §10 do requisito são mapeados como **bounded contexts (módulos de domínio)** dentro de um único deployable. Ver [ADR-0001](../adrs/ADR-0001-runtime-architecture.md).

| Plane (requisito §10) | Módulo de domínio | Responsabilidade |
|---|---|---|
| Control Plane | `control` | OrchestratorRuntime, PhaseController, MultiAgentDecisionEngine, AgentSupervisor, AgentRouter, ExecutionPlanner, DependencyGraph, HumanApprovalEngine |
| Kanban Plane | `kanban` | Board, Card, Swimlane, dependências, assignment, eventos de card |
| Agent Plane | `agents` | AgentRegistry, AgentSupervisor, AgentExecutor, AgentAdapterRegistry, SkillRegistry/Resolver, ToolPermissionEngine |
| Execution Plane | `execution` | ExecutionProvider (Local/Mock, Cli, AgentWrapper), WorktreeManager, TerminalRuntime, PR/CI/Review observers |
| Governance Plane | `governance` | OrchestratorContext, ContextBus, ContextPatchValidator, ConflictDetector, QualityGateEngine, ADRRegistry, SnapshotEngine, ContractValidator |
| Observability Plane | `observability` | TraceService, EventLog, CostTracker, TokenUsageTracker, AgentRunTimeline, AuditLog |

**Regra de dependência (Clean Architecture):** domínio de cada plane não depende de infraestrutura; API, CLI e DB são *adapters*. `governance` é o núcleo soberano — nenhum outro módulo escreve no contexto sem passar pelo `ContextBus`.

## 2. Mapa de camadas

```
driving adapters:   api (FastAPI)   |   cli (Typer)
                          │
application:        casos de uso por plane (orquestrar, criar card, rotear agente, aplicar patch, rodar gate...)
                          │
domain:             control · kanban · agents · execution · governance · observability
                          │
driven adapters:    db (SQLAlchemy/Postgres) · llm_providers (httpx) · cli_agents (subprocess/pty) · git (worktrees)
```

## 3. Stack técnica (locked)

Ver [ADR-0004](../adrs/ADR-0004-tech-stack-python.md).

| Camada | Escolha |
|---|---|
| Linguagem | Python 3.12+ |
| API | FastAPI + Uvicorn |
| Modelos/validação | Pydantic v2 (contexto, patches, DTOs, contratos) |
| Persistência | PostgreSQL 16 (JSONB para contexto/snapshots) + SQLAlchemy 2.x + Alembic |
| Concorrência | asyncio; limites de concorrência configuráveis (§26A.10) |
| LLM providers | `httpx` (OpenAI-compatible: DeepSeek/OpenAI), SDK Anthropic; abstração `LLMProvider` |
| CLI agents | `subprocess`/PTY via `AgentAdapter` (Claude Code, Codex, Aider) |
| Git/worktrees | `git` via subprocess (`WorktreeManager`) |
| CLI | Typer |
| Testes | pytest + pytest-asyncio + coverage |
| Qualidade | ruff (lint+format) + mypy (type-check) |
| Empacotamento | `pyproject.toml` (uv/pip), `src/` layout |
| Infra local | Docker Compose (Postgres) |
| UI web | **diferida** — frontend separado consumindo a API (MVP posterior); MVP 1 entrega API + CLI |

## 4. Estrutura de projeto proposta

```
aso-runtime/
  pyproject.toml
  docker-compose.yml
  src/aso/
    control/         # Control Plane (domínio + casos de uso)
    kanban/          # Kanban Plane
    agents/          # Agent Plane (registry, executor, adapters, skills, tools)
    execution/       # Execution Plane (providers, worktrees, terminal, git, pr, ci)
    governance/      # Governance Plane (context, contextbus, gates, adrs, snapshots, conflicts)
    observability/   # Observability Plane (traces, events, cost, tokens, timeline, audit)
    shared/          # types, schemas (pydantic), events, utils
    api/             # FastAPI (driving adapter)
    cli/             # Typer (driving adapter)
    db/              # SQLAlchemy models + migrations (driven adapter)
  tests/
    unit/  integration/
  docs/
```

## 5. Modelo de dados (macro) e persistência

- **OrchestratorContext e snapshots**: persistidos como **JSONB** em Postgres (leitura/escrita atômica, versionamento por linha + histórico append-only). Consistência **forte** dentro de uma orquestração.
- Tabelas relacionais para entidades operacionais (§29): `orchestrations`, `boards`, `kanban_cards`, `agents`, `agent_runs`, `context_patches`, `conflicts`, `quality_gate_results`, `snapshots`, `adrs`, `human_approvals`, `audit_events`, `cost_records` etc.
- Detalhamento fino de schemas e OpenAPI → **F3**.

## 6. Integrações externas (catálogo)

| Integração | Tipo | Contrato | Segurança |
|---|---|---|---|
| LLM Providers (DeepSeek, OpenAI, Anthropic, local) | HTTP API | `LLMProvider` (OpenAI-compatible + nativo) | `api_key_env`, nunca em texto puro, teste sem revelar segredo |
| CLI Agents (Claude Code, Codex, Aider) | processo local | `AgentAdapter` (§27) | worktree obrigatório para escrita; sem comando destrutivo sem aprovação |
| Git | processo local | `WorktreeManager` / git diff | branch/worktree por card; sem push em main sem aprovação |
| CI / PR / Review | observadores | `CIObserver`, `PullRequestManager`, `ReviewObserver` | diferido p/ MVP 3–4 |

## 7. Modelo de segurança

- **Secrets:** apenas via variáveis de ambiente / `.env` (fora do versionamento); UI/logs nunca exibem chave completa (§26A.10).
- **Permissões de tools por agente** (`ToolPermissionEngine`): allowlist por papel; `requires_approval_for` para ações críticas.
- **HumanApprovalEngine** obrigatório para: deletar arquivos, alterar secrets, resetar banco, deploy, alterar branch principal, modificar contrato público, sobrescrever snapshot, ignorar gate, alterar ADR aceita, shell perigoso, publicar mensagem externa, ação de alto custo, resolver conflito crítico sem consenso.
- **Isolamento:** worktree/sandbox por agente que altera código; isolamento por projeto.
- **Validação de I/O:** Pydantic valida toda entrada/saída; outputs de agentes só entram no contexto como `ContextPatch` validado.
- **Threat model básico:**
  - *Prompt/output injection* de agentes → mitigado por validação de `ContextPatch` + ConflictDetector + gates.
  - *Command injection* → allowlist de tools, sem shell destrutivo sem aprovação.
  - *Secret leakage* → mascaramento, env-only, audit log.
- **Auditoria:** `AuditLog` registra ator, agente, ação, payload, decisão.
- **Limites:** custo, iterações e tempo por execução; concorrência por projeto/orquestração.

## 8. Estratégia de infraestrutura

- **Local-first**: roda na máquina do desenvolvedor; Docker Compose sobe Postgres.
- **Processo único** (API + workers asyncio) no MVP 1–2; extração de workers/serviços apenas se houver gargalo (validado por `performance-and-scale-engine` em F7).
- **Escala:** vertical primeiro; limites de concorrência configuráveis; sem execução remota distribuída no MVP.

## 9. Estratégia de observabilidade

- Logs estruturados (JSON) com `orchestration_id`/`card_id`/`agent_run_id` como correlation IDs.
- `EventLog` append-only para eventos de domínio (movimentação de card, patch aplicado, gate executado, snapshot gerado).
- `CostTracker` + `TokenUsageTracker` por execução/provider.
- `AgentRunTimeline` para a timeline da orquestração.
- Tracing (OpenTelemetry) previsto; instrumentação plena em F5/F7.

## 10. Riscos técnicos

| ID | Risco | Mitigação |
|---|---|---|
| TRISK-01 | JSONB para contexto pode dificultar queries relacionais complexas | Entidades operacionais em tabelas relacionais; JSONB só p/ contexto/snapshots |
| TRISK-02 | Concorrência asyncio + escrita única no contexto pode gerar contenção | Locks por `target_keys` no ContextBus + fila do ConflictDetector |
| TRISK-03 | Heterogeneidade dos CLI agents dificulta o `AgentAdapter` único | Contrato §27 abstrato; começar por Local/Mock provider |
| TRISK-04 | Divergência da stack sugerida (§37 TS) pode confundir contribuintes | ADR-0004 documenta override; §37 marcado como superado |

## 11. ADRs registrados nesta fase

- [ADR-0001 — Arquitetura do runtime (Modular Monolith + Hexagonal + planes como bounded contexts)](../adrs/ADR-0001-runtime-architecture.md)
- [ADR-0002 — Kanban como plano de execução](../adrs/ADR-0002-kanban-as-execution-plane.md)
- [ADR-0003 — ContextBus como governança soberana do contexto](../adrs/ADR-0003-contextbus-governance.md)
- [ADR-0004 — Stack de implementação: Python](../adrs/ADR-0004-tech-stack-python.md)

## 12. Quality Gate F2 → F3

| Critério | Status | Evidência |
|---|---|---|
| Padrão arquitetural com ADR | ✅ PASSED | ADR-0001; seção 1 |
| Stack locked com justificativa | ✅ PASSED | ADR-0004; seção 3 |
| Modelo de segurança definido | ✅ PASSED | Seção 7 |
| Estratégia de infraestrutura definida | ✅ PASSED | Seção 8 |
| Contratos de integração externos catalogados | ✅ PASSED | Seção 6 |
| Nenhuma decisão contraditória (ConflictDetector) | ✅ PASSED* | *Override do §37 resolvido via ADR-0004 |

**Resultado: PASSED → snapshot O2 gerado. Apto a avançar para F3 (Data & API Contracts) mediante aprovação.**
