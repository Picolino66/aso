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

### Modo híbrido — `manager.sh` (Postgres no Docker, API local)

Jeito mais fácil no dia a dia: o **Postgres roda no Docker** e a **API roda local** na
venv (servindo o console em `/ui`). Um único painel cuida de tudo:

```bash
./scripts/manager.sh            # menu interativo (iniciar/parar/logs/status/…)
./scripts/manager.sh iniciar    # sobe o Postgres, aplica migrations e sobe a API local
./scripts/manager.sh status     # estado do banco + API + /health
./scripts/manager.sh logs       # segue os logs da API local
./scripts/manager.sh parar      # para a API e o Postgres (dados preservados)
```
Console em **http://localhost:8000/ui**. Na 1ª execução, o script cria a venv e instala
as dependências (incluindo o driver `psycopg`) se faltarem. Comandos extras: `reiniciar`,
`db-logs`, `migrate`, `test`, `check`, `psql`, `shell`, `seed`.

**Cadastrar Codex + Claude de uma vez** (todos os modelos × níveis low/medium/high):
```bash
./scripts/manager.sh seed
```
Cria os perfis via `scripts/seed-executors.sh` (edite os arrays de modelos conforme sua
instalação). Para **executar** os agentes: `export ASO_TARGET_REPO=/repo` antes de iniciar
e tenha os binários `codex`/`claude` no PATH. Os comandos já usam o wrapper com o caminho
**entre aspas** (necessário porque o projeto fica sob "Área de trabalho").

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
| `ASO_SLO_FAILURE_BUDGET` | orçamento de erro da taxa de falhas de execução no `/slo` (default 0.10) |
| `ASO_MAX_SLO_SAMPLES` | retenção de amostras de SLO por orquestração (default 200) |
| `ASO_LLM_PROVIDER` / `ASO_LLM_API_KEY` / `ASO_LLM_MODEL` | cérebro do autopilot: `deepseek`/`openai`/`anthropic` + chave + modelo (planejamento via `POST .../plan`) |
| `ASO_LLM_BASE_URL` | URL base do provedor LLM (opcional; default por provedor) |
| `ASO_GATE_TEST_COMMAND` | comando de testes/lint rodado no gate das fases de código (F5/F6) no `ASO_TARGET_REPO`; só aprova com exit 0 |
| `ASO_EXECUTORS` | catálogo JSON de executores (seed inicial); ex.: `[{"name":"claude","kind":"cli","command":"claude -p","model":"sonnet"}]`. Também editável pela tela **⚙ Config** do console |
| `ASO_EXECUTORS_FILE` | arquivo onde a tela de config persiste os perfis (default `.aso/executors.json`; monte um volume para persistir no Docker) |
| `ASO_<NOME>_API_KEY` | chave do executor LLM chamado `<nome>` (a tela de config só referencia a env var; o segredo nunca é gravado) |

### Configurar o Codex (ou Claude CLI) para todas as fases

Ao **selecionar um agente** no dropdown do console e clicar **▶ Autopilot**, ele é usado
em **todas as fases** (F1→F7) — a escolha se propaga automaticamente pela cadeia de
aprovações. Passos:

1. **Repo alvo** (obrigatório p/ agentes CLI): `export ASO_TARGET_REPO=/caminho/do/repo`.
2. Garanta que o binário (`codex`/`claude`) está **acessível ao processo da API** (rodando
   local via `uvicorn`, é o seu ambiente; no Docker, precisa estar na imagem).
3. Na tela **⚙ Config**, adicione o executor:
   - **nome**: `codex` · **tipo**: `cli` · **default**: marcado
   - **comando CLI** (caminho absoluto do wrapper + o agente):
     `/app/scripts/aso-agent-wrapper.sh codex exec` (ou, local, o caminho do repo)
4. O **wrapper** [`scripts/aso-agent-wrapper.sh`](scripts/aso-agent-wrapper.sh) traduz a
   tarefa (JSON no stdin) em um prompt em pt-BR e chama `codex exec "<prompt>"` no worktree
   do card. Para o Claude Code, use `... aso-agent-wrapper.sh claude -p`.

> **Caminho com espaços**: o comando do executor é separado por `shlex`, então um caminho
> com espaços (ex.: `Área de trabalho`) precisa estar **entre aspas**:
> `"/home/eu/Área de trabalho/.../aso-agent-wrapper.sh" codex exec`. Sem aspas, ele quebra e
> o card falha (o motivo aparece no próprio card).
>
> **Quer só ver a esteira gerando código de verdade, sem chave/LLM?** Use o agente de
> demonstração [`scripts/demo-agent.sh`](scripts/demo-agent.sh): cadastre um executor `cli`
> com esse comando (entre aspas) e `ASO_TARGET_REPO` apontando para um repo git — ele
> escreve um módulo real + teste, que passa por PR e merge governado.

> Observação: um CLI de código roda em todas as fases se você escolher, mas em F1–F4
> (discovery/arquitetura) o ideal é um LLM de planejamento; deixe o codex focado em F5–F6
> se quiser melhor resultado.

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
