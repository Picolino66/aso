# ASO Runtime — Autonomous Software Orchestrator Runtime

Runtime de **engenharia de software autônoma e orquestração multiagente**. O ASO
coordena múltiplos agentes de código (Claude Code, Codex, Aider, …) ao longo do
ciclo de vida completo de um produto — das fases de discovery (F1) à operação e
evolução em produção (F7) — mantendo **governança de contexto soberana**, um
**Kanban como plano de execução**, **ADRs**, **quality gates** e **snapshots**
imutáveis por fase.

> Toda a documentação, a UI e os comentários de código estão em **português do
> Brasil (pt-BR)**.

---

## Por que o ASO existe

Ferramentas de agentes de código executam tarefas isoladas, mas perdem o contexto
global do produto entre execuções, contrariam decisões arquiteturais e conflitam
entre si quando atuam em paralelo. O ASO resolve isso com uma camada de
governança em que **nenhum agente altera o estado canônico diretamente** — toda
mudança passa por um `ContextPatch` validado pelo **ContextBus** (single-writer,
deny-by-default).

## Princípios de governança

- **ContextBus é o único escritor** do contexto canônico. Patches passam por um
  pipeline de validação de 8 etapas (schema, permissão, conflito, lock de
  snapshot, consistência/contradição de ADR, compatibilidade de contrato,
  impacto em quality gate).
- **Não avança de fase** com quality gate reprovado.
- **Ações de alto risco exigem aprovação humana** (merge, rollback, aprovações).
- **Agentes que alteram código rodam em worktree git isolado**, nunca na branch
  principal; o diff é coletado antes de qualquer merge governado.
- **Rastreabilidade total**: requisito → ADR → spec → card → implementação →
  teste → gate → snapshot.
- **Secrets apenas via variáveis de ambiente**, nunca no repositório.

---

## Arquitetura

Monólito modular com Hexagonal (Ports & Adapters) + DDD. Seis planes como módulos
sob [src/aso/](src/aso/):

| Plane | Responsabilidade |
|---|---|
| `control` | OrchestrationService, MultiAgentDecisionEngine, ExecutionPlanner, run_plan (ondas topológicas), aprovações |
| `kanban` | Board, cards, colunas e automação por eventos |
| `agents` | AgentRegistry, AgentSupervisor (retry/nudge), ExecutionProvider |
| `execution` | WorktreeManager, CliAgentExecutionProvider, CandidateRunner (candidatos CLI paralelos), PR/CI/review + merge governado |
| `governance` | ContextBus, ContextPatch, ConflictDetector, ADRRegistry, QualityGateEngine, SnapshotEngine |
| `observability` | logs estruturados (structlog), rate limiting, tracing (OTel), métricas Prometheus, EventBroker (SSE) |

Adapters de entrada: **API** (FastAPI, [src/aso/api/](src/aso/api/)) e **CLI**
(Typer, [src/aso/cli/](src/aso/cli/)). Adapter de saída de persistência:
in-memory + **SQLAlchemy/Postgres** com esquema normalizado e migrations Alembic
([migrations/](migrations/)).

### Stack

Python 3.12 · Pydantic v2 · FastAPI + Uvicorn · Typer · SQLAlchemy 2.x + Alembic ·
PostgreSQL 16 (JSONB) / SQLite (testes) · structlog · OpenTelemetry (opcional) ·
pytest · ruff · mypy --strict.

---

## Começando

### Com Docker (recomendado)

Sobe Postgres + API (migrations no boot, healthcheck `/health`):

```bash
docker compose up -d --build
curl -s localhost:8000/health          # {"status":"ok"}
```

Console web em **http://localhost:8000/ui** · OpenAPI em `/docs`.

Smoke end-to-end contra o Postgres:

```bash
./scripts/smoke.sh
```

Encerrar (limpando o volume):

```bash
docker compose down -v
```

### Local (desenvolvimento)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,postgres,security,otel]"
alembic upgrade head          # aplica migrations (SQLite por padrão)
uvicorn aso.api.app:create_app --factory --reload
```

---

## Uso

### CLI (`aso`)

```bash
aso run "implementar autenticação no backend"   # cria orquestração e executa o pipeline
aso cards <orchestration_id>                     # lista cards do Kanban
aso timeline <orchestration_id>                  # timeline de eventos
aso adrs <orchestration_id>                      # ADRs registradas
aso metrics <orchestration_id>                   # métricas + SLOs
aso approvals <orchestration_id>                 # aprovações pendentes
aso approve <approval_id>                        # aprova ação crítica
aso rollback <orchestration_id> <snapshot>       # rollback para snapshot estável
aso stats <orchestration_id>                     # agregações (CQRS-lite)
aso feedback <orchestration_id> "texto"          # feedback → backlog
```

### API v1 (destaques)

```
POST /v1/orchestrations                         # cria orquestração
POST /v1/orchestrations/{id}/run-plan           # executa o plano (ondas topológicas)
POST /v1/orchestrations/{id}/cards/{cid}/run    # executa um card
GET  /v1/orchestrations/{id}/context            # contexto canônico atual
GET  /v1/orchestrations/{id}/kanban ...cards    # Kanban
POST .../cards/{cid}/open-pr                     # abre PR do worktree do card
POST .../pulls/{pr}/ci | /review | /merge        # CI/review/merge governado (merge = admin)
POST .../conflicts/{cid}/resolve                 # resolução de conflito
POST .../approvals/{aid}/approve | /reject       # aprovação humana
GET  .../events/stream                           # SSE ao vivo (console)
GET  /metrics                                    # exposição Prometheus
```

Console SPA em `/ui`: dashboard, Kanban, timeline, ADRs, aprovações, snapshots
(diff), patches, conflitos, métricas e **PRs**.

### Autenticação / RBAC

Chaves via `ASO_API_KEYS` (JSON, papéis `viewer` < `operator` < `admin`).
Endpoints críticos (`/merge`, `/approve`, `/reject`, `/rollback`) exigem `admin`.
Rotas públicas: `/health`, `/metrics`, `/`, `/ui`, `/docs`.

| Variável | Descrição |
|---|---|
| `ASO_DATABASE_URL` | URL do banco (default SQLite; Postgres no Docker) |
| `ASO_API_KEYS` | mapa JSON de chave → papel |
| `ASO_RATE_LIMIT` | limite de requisições por IP |
| `ASO_OTEL` | `1` habilita tracing OpenTelemetry (extra `[otel]`) |
| `ASO_CLI_COMMAND` / `ASO_TARGET_REPO` | comando do agente CLI e repo alvo dos worktrees |
| `ASO_CANDIDATE_COMMANDS` | JSON de agentes CLI candidatos para corrida por card (§26A.6); ver `scripts/e2e_candidates.sh` |
| `ASO_MAX_RACES_PER_CARD` | retenção de corridas de candidatos por card (default 20) |

---

## Qualidade

```bash
ruff check src tests          # lint
ruff format --check src tests # formatação
mypy src                      # tipagem estrita
alembic check                 # migrations em dia
pytest -q --cov=src/aso --cov-fail-under=80
```

Estado atual: **114 testes verdes**, cobertura **~96%**, ruff/mypy limpos,
`alembic check` sem diffs, Docker e2e validado no Postgres. CI em
[.github/workflows/ci.yml](.github/workflows/ci.yml); release por tag no GHCR em
[.github/workflows/release.yml](.github/workflows/release.yml).

---

## Estrutura do repositório

```
src/aso/          # runtime (planes control/kanban/agents/execution/governance/observability + api/cli/db)
docs/             # documentação canônica (fonte de verdade) — adrs/, phases/
specs/            # specs executáveis por task
tasks/ agents/ skills/   # backlog, mapa de agentes, mapa de skills
contracts/        # openapi.yaml (v1)
migrations/       # Alembic
tests/            # unit/ + integration/
.aso/             # estado do runtime: context, kanban/board.json, snapshots, quality-gates
```

Contexto canônico de governança: [.aso/context/orchestrator-context.json](.aso/context/orchestrator-context.json).
Board Kanban: [.aso/kanban/board.json](.aso/kanban/board.json).

## Documentação

- Requisitos originais: [requerimentos.md](requerimentos.md)
- Histórico de mudanças: [CHANGELOG.md](CHANGELOG.md)
- Guia para agentes de IA neste repositório: [CLAUDE.md](CLAUDE.md)
- Índice de docs: [docs/index.md](docs/index.md) · ADRs: [docs/adrs/](docs/adrs/) ·
  fases F1–F7: [docs/phases/](docs/phases/) · operação/deploy:
  [docs/operations.md](docs/operations.md), [docs/deploy.md](docs/deploy.md)

## Roadmap

MVP-1 (core de governança) → MVP-2 (multiagente real: paralelo, supervisor,
review, conflitos, aprovações) → MVP-3 (execution plane: worktrees, git, diff) →
MVP-4 (PR/CI/review + merge governado + candidatos CLI paralelos) → MVP-5 (produto
completo, UI completa, operação F7 avançada).
