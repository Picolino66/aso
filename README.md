# ASO Runtime — Autonomous Software Orchestrator Runtime

Runtime de **engenharia de software autônoma e orquestração multiagente**. O ASO
coordena múltiplos agentes de código (Claude Code, Codex, Aider, …) ao longo do
ciclo de vida completo de um produto — das fases de discovery (F1) à operação e
evolução em produção (F7) — mantendo **governança de contexto soberana**, um
**Kanban como plano de execução**, **ADRs**, **quality gates** e **snapshots**
imutáveis por fase.

> Toda a documentação, a UI e os comentários de código estão em **português do
> Brasil (pt-BR)**.

> **Chegou agora?** Comece por [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) — glossário,
> fluxo de uma demanda e onde mexer — e depois [docs/GOVERNANCE.md](docs/GOVERNANCE.md).

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
  pipeline de validação de 6 etapas (schema, permissão, lock de snapshot,
  consistência/contradição de ADR, compatibilidade de contrato).
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
Console em **http://localhost:8000/ui**. Cadastre um projeto (uma pasta canônica por
projeto) e use **Nova orquestração**: projeto → pré-análise somente leitura → demanda e
configuração → docs-first → detalhe. O Autopilot só começa quando for acionado no detalhe.
Na 1ª execução, o script cria a venv e instala
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

> **Limite atual:** a imagem Docker não inclui `scripts/` (wrapper de agentes) nem os binários
> `codex`/`claude`; agentes CLI reais rodam no modo local (`manager.sh`/venv). No Docker, use
> executores mock ou LLM via API.

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
aso restaurar-ledger <orchestration_id> --to O3  # restaura só o ledger do contexto (alias: rollback)
aso stats <orchestration_id>                     # agregações (CQRS-lite)
aso feedback <orchestration_id> "texto"          # feedback → backlog
```

### API v1 (destaques)

```
POST /v1/orchestrations                         # cria orquestração
GET/POST /v1/projects                           # catálogo multi-repo
PATCH/DELETE /v1/projects/{id}                  # editar / arquivar sem cascata
POST /v1/projects/{id}/restore                  # restaurar projeto (admin)
GET  /v1/projects/{id}/events                   # histórico auditável
GET  /v1/orchestrations?project_id={id}          # filtra por projeto
POST /v1/orchestrations/{id}/run-plan           # executa o plano (ondas topológicas)
POST /v1/orchestrations/{id}/cards/{cid}/run    # executa um card
GET  /v1/orchestrations/{id}/context            # contexto canônico atual
GET  /v1/orchestrations/{id}/kanban ...cards    # Kanban
POST .../cards/{cid}/open-pr                     # abre PR do worktree do card
POST .../pulls/{pr}/ci/run | /ci | /review/run | /review | /merge  # CI executada/declarada (ADR-0056), revisão (ADR-0017), merge (admin)
GET  .../cards/{cid}/failures | POST .../cards/{cid}/route  # roteamento de falha (ADR-0019)
GET  .../cards/{cid}/closure                     # ficha de encerramento (ADR-0021, §23)
GET/POST .../discovery | .../discovery/run | .../discovery/decide  # discovery (ADR-0020)
GET/POST .../spec | .../spec/run | .../spec/review | .../spec/approve  # especificação (ADR-0021)
GET/PUT .../validation-checks | GET .../validation-checks/suggest  # bateria de validações (ADR-0022, §12)
GET/PUT .../deploy | .../deploy/history  # implantação governada (ADR-0023, §18-22)
POST .../deploy/run | /validate | /approve | /rollback  # executa, valida, aceite final, rollback
GET/POST .../cards/{cid}/qa | POST .../qa/{i}/fail  # QA manual (ADR-0025, §16/§17)
GET  .../learning | GET /v1/learning              # aprendizado da esteira (ADR-0025, §24; custo real, ADR-0026)
PUT  .../budget                                  # eleva/remove teto de gasto; admin (ADR-0026)
GET  .../worktrees | POST .../worktrees/prune    # worktrees órfãos após crash; prune admin (ADR-0027)
POST .../conflicts/{cid}/resolve                 # resolução de conflito
POST .../approvals/{aid}/approve | /reject       # aprovação humana
GET  .../events/stream                           # SSE ao vivo (console)
GET  /metrics                                    # exposição Prometheus
```

Console em `/ui/`: catálogo de projetos ativos/arquivados e Kanban agrupado. Clicar num
card abre `/ui/detalhe?id=…`, a **sala de controle** daquela orquestração: esteira F1→F7,
card **"Próximo passo"** (o que falta e qual é o clique, vindo de
`GET .../next-step`), painel **"Ficha da demanda"** (tipo, objetivo, domínios, impactos,
riscos e complexidade, produzidos por triagem — agente ou heurística — antes de criar a
orquestração; ADR-0016), painel **"Revisão de código"** quando há PR aberta (veredito,
revisor — sempre diferente de quem implementou —, ações obrigatórias/sugestões e
pontos verificados por um agente independente sobre o diff real; ADR-0017), painel **"o
que o agente está fazendo"** com a saída do CLI em tempo real, funil só da fase
corrente, pendências de governança acionáveis e atividade ao vivo por SSE. Cada etapa
da esteira mostra o que é, o que entrega e **qual agente a executa** —
clicar no chip troca o agente daquela fase, então F1 pode rodar num modelo barato e F5 no
mais forte, na mesma orquestração. Essa sala de controle é a seção **Esteira** (`/ui/esteira?id=`);
a auditoria técnica — timeline, ADRs, aprovações, snapshots (diff), patches, conflitos, corridas de
candidatos, custos e PRs — fica nas abas de `/ui/demanda-detalhe` (ADR-0078). As rotas antigas
(`/ui/`, `/ui/nova`, `/ui/detalhe`, `/ui/console`) redirecionam para as seções equivalentes.

Para o painel mostrar ferramenta por ferramenta (e não só a resposta final do agente), marque
**streaming** no perfil do executor (⚙ Config): o ASO monta `--output-format stream-json
--verbose` para o Claude e `--json` para o Codex (ADR-0076).

As branches criadas pelo runtime saem do **título do card**:
`feat/calculadora-basica-a1b2c3d4` (ADR-0014). Para recomeçar do zero,
`./scripts/reset.sh` zera o banco e os worktrees preservando a governança versionada e o
catálogo de executores.

### Autenticação / RBAC

Chaves via `ASO_API_KEYS` (JSON, papéis `viewer` < `operator` < `admin`). Sem chaves a
API só sobe com `ASO_DEV_MODE=1` (ADR-0057). Endpoints críticos (`/merge`, `/approve`,
`/reject`, `/restaurar-ledger` (alias `/rollback`), `/advance-phase`, arquivar/restaurar projeto) e os que configuram
ou disparam comandos no host (`validation-checks`, `deploy/*`) exigem `admin`.
Rotas públicas: `/health`, `/metrics`, `/`, `/ui`, `/docs`.

| Variável | Descrição |
|---|---|
| `ASO_DATABASE_URL` | URL do banco (default SQLite; Postgres no Docker) |
| `ASO_API_KEYS` | mapa JSON de chave → papel |
| `ASO_DEV_MODE` | `1` libera o modo dev (admin anônimo) quando não há `ASO_API_KEYS`; sem ele a API não sobe |
| `ASO_RUN_RETENCAO_DIAS` | dias até limpar prompt/stdout dos registros de execução (`agent_runs`); sem a variável, nada é limpo |
| `ASO_CONTEXTO_MAX_CHARS` | orçamento de caracteres do contexto entregue ao agente (padrão 12000, ADR-0063) |
| `ASO_WORKSPACE_ROOTS` | raízes permitidas para pastas de trabalho e `/v1/fs/*` (separadas por `:`; default `$HOME`) |
| `POSTGRES_PASSWORD` | senha do Postgres no compose (default `aso`, só local) |
| `ASO_RATE_LIMIT` | limite de requisições por IP |
| `ASO_OTEL` | `1` habilita tracing OpenTelemetry (extra `[otel]`) |
| `ASO_TARGET_REPO` | repo alvo dos worktrees de orquestrações sem pasta própria |
| `ASO_CLI_COMMAND` | **só semeia** o catálogo sem arquivo salvo: perfil `cli` (ADR-0076) |
| `ASO_CANDIDATE_COMMANDS` | **só semeia** o catálogo: perfis CLI marcados `candidato` da corrida (§26A.6, ADR-0076) |
| `ASO_MAX_RACES_PER_CARD` | retenção de corridas de candidatos por card (default 20) |
| `ASO_SLO_FAILURE_BUDGET` | orçamento de erro da taxa de falhas de execução no `/slo` (default 0.10) |
| `ASO_MAX_SLO_SAMPLES` | retenção de amostras de SLO por orquestração (default 200) |
| `ASO_ORCAMENTO_PADRAO_USD` | teto de gasto (US$) de orquestrações novas (ADR-0026); sem a variável, sem teto |
| `ASO_LLM_PROVIDER` / `ASO_LLM_MODEL` / `ASO_LLM_BASE_URL` | **só semeiam** o catálogo: perfil `llm` (`deepseek`/`openai`/`anthropic`) usado no planejamento (ADR-0076) |
| `ASO_LLM_API_KEY` | chave do perfil `llm` semeado (o perfil guarda só o nome da variável) |
| `ASO_GATE_TEST_COMMAND` | comando de testes/lint rodado no gate das fases de código (F5/F6) no `ASO_TARGET_REPO`; só aprova com exit 0 |
| `ASO_EXECUTORS` | catálogo JSON de executores (seed inicial; o catálogo salvo em `ASO_EXECUTORS_FILE` vence); ex.: `[{"name":"claude","kind":"cli","command":"claude -p","model":"sonnet"}]`. Também editável pela tela **⚙ Config** do console |
| `ASO_EXECUTORS_FILE` | arquivo onde a tela de config persiste os perfis (default `.aso/executors.json`; monte um volume para persistir no Docker) |
| `ASO_CODEX_BIN` | binário Codex consultado por `model/list` e usado nos perfis gerenciados (default `codex` do `PATH`) |
| `ASO_<NOME>_API_KEY` | chave do executor LLM chamado `<nome>` (a tela de config só referencia a env var; o segredo nunca é gravado) |

### Configurar o Codex (ou Claude CLI) para todas as fases

Ao **selecionar um agente** no dropdown do console e clicar **▶ Autopilot**, ele é usado
em **todas as fases** (F1→F7) — a escolha se propaga automaticamente pela cadeia de
aprovações. Passos:

1. **Repo alvo** (obrigatório p/ agentes CLI): `export ASO_TARGET_REPO=/caminho/do/repo`.
2. Garanta que o binário (`codex`/`claude`) está **acessível ao processo da API** (rodando
   local via `uvicorn`, é o seu ambiente; no Docker, precisa estar na imagem).
3. Rode `./scripts/manager.sh seed`: o ASO cria `codex-default` e um perfil por modelo
   anunciado pela conta, sem copiar uma lista estática que pode divergir do rollout.
4. Para um executor personalizado, use a tela **⚙ Config**:
   - **nome**: `codex` · **tipo**: `cli` · **default**: marcado
   - **comando CLI** (caminho absoluto do wrapper + o agente):
     `/app/scripts/aso-agent-wrapper.sh codex exec` (ou, local, o caminho do repo)
5. O **wrapper** [`scripts/aso-agent-wrapper.sh`](scripts/aso-agent-wrapper.sh) traduz a
   tarefa (JSON no stdin, contrato `TaskEnvelope` v1 — ADR-0059) em um prompt em pt-BR via
   `src/aso/agents/render_prompt.py` e chama `codex exec "<prompt>"`. Execução de card
   recebe critérios, correções, contexto adicional e `nudge`; perguntas (naming, triagem,
   discovery, spec, revisão) recebem o `system` completo e respondem só JSON — também com
   `--output-format stream-json`. Para o Claude Code, use `... aso-agent-wrapper.sh claude -p`.

> **Permissão de escrita (causa nº 1 de card `Blocked` com "diff vazio", ADR-0019)**: em modo
> não-interativo os CLIs não editam arquivos sem autorização explícita — respondem em texto,
> saem com 0 e o worktree fica intacto. Use `claude -p --permission-mode acceptEdits` (só
> edições) ou `--dangerously-skip-permissions` (edições + comandos, necessário para rodar
> build/testes); os perfis Codex gerenciados já vêm com permissão `edicoes`. Hoje isso é o
> campo **permissão de escrita** do perfil (⚙ Config: nenhuma, edições ou total) — o ASO monta
> a flag de cada CLI e perfis antigos com a flag no comando são migrados no boot. Detalhes em
> [docs/operations.md](docs/operations.md#permissão-de-escrita-do-agente-cli-causa-nº-1-de-diff-vazio).

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

O número de testes e a cobertura atuais são reportados pelo CI (mínimo exigido: 80%). CI em
[.github/workflows/ci.yml](.github/workflows/ci.yml); release por tag no GHCR em
[.github/workflows/release.yml](.github/workflows/release.yml).

---

## Estrutura do repositório

```
src/aso/          # runtime (planes control/kanban/agents/execution/governance/observability + api/cli/db)
docs/             # documentação canônica (fonte de verdade) — adrs/, phases/
specs/            # specs executáveis por task
tasks/ agents/ skills/   # backlog, mapa de agentes, mapa de skills
contracts/        # openapi.json gerado das rotas (python scripts/export-openapi.py; ADR-0064)
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
