# Operações — ASO Runtime (Runbook)

> Fase F6. Procedimentos operacionais mínimos. Observabilidade via EventLog/timeline (§33).

## Executar localmente

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python -m aso.cli.main run "Criar módulo X"   # ciclo completo (mock)
uvicorn aso.api.app:app         # API v1 em :8000 (docs em /docs)
```

## Stack completa em Docker (recomendado — sem dependências na máquina)

```bash
docker compose up --build        # sobe Postgres + API (migrations aplicadas no boot)
bash scripts/smoke.sh http://localhost:8000   # smoke end-to-end
docker compose down -v           # derruba tudo e limpa o volume
```

A API fica em `http://localhost:8000` (Swagger em `/docs`). O healthcheck usa `/health`.
Validado localmente contra Postgres real (smoke OK). O mesmo fluxo roda no CI (job `smoke-docker`).

## Banco de dados

- Sem `ASO_DATABASE_URL`: persistência **in-memory** (volátil) — só dev.
- Com `ASO_DATABASE_URL`: SQLite ou Postgres.

```bash
export ASO_DATABASE_URL="postgresql+psycopg://aso:aso@localhost:5432/aso"
docker compose up -d postgres   # sobe o Postgres local
alembic upgrade head            # aplica o schema
```

### Recomeçar do zero

```bash
./scripts/reset.sh              # pergunta antes; --sim pula a confirmação
./scripts/reset.sh --executores # e também apaga o catálogo .aso/executors.json
```

Apaga o volume do Postgres (schema recriado por Alembic), os worktrees órfãos de
`.aso/worktrees` (sempre via `git worktree remove` — `rm -rf` deixaria refs órfãs em
`.git/worktrees`), `.aso/run` e o `aso.db` — resíduo do fallback `sqlite:///aso.db` em
[migrations/env.py](../migrations/env.py), criado por qualquer `alembic` rodado sem
`ASO_DATABASE_URL`.

**Não apaga** a governança versionada do próprio ASO (`.aso/context`, `.aso/kanban`,
`.aso/quality-gates`, `.aso/snapshots`, `.aso/reviews`) nem `.aso/executors.json` — o
catálogo de executores vive em arquivo, fora do banco, então seus perfis Claude/Codex
sobrevivem a qualquer reset. Os repositórios-alvo também ficam intactos: o script lista os
`target_path` **antes** do drop (eles só existem no banco) e imprime o comando de limpeza
de cada um, deixando a decisão com você — essas branches guardam trabalho real.

## Migrations (Alembic)

```bash
alembic upgrade head            # aplicar todas
alembic downgrade -1            # reverter a última
alembic current                 # revisão atual
alembic history                 # histórico
alembic check                   # schema == modelos ORM?
alembic revision --autogenerate -m "descricao"   # nova migration
```

A revisão `f84c2a1d9e30` cria o catálogo relacional. IDs legados são convertidos em
projetos arquivados; conflitos de path ficam sem pasta e precisam de restauração
administrativa. Não remova projetos por SQL: use `DELETE /v1/projects/{id}` para arquivar
e preservar as FKs, ou `POST /restore` para reativar.

## Qualidade (gates locais = CI)

```bash
ruff check src tests && ruff format --check src tests
mypy src
pytest -q --cov=src/aso --cov-fail-under=80
bandit -r src -q                # SAST
pip-audit --skip-editable       # SCA
```

## Autenticação e RBAC (§34)

- Sem `ASO_API_KEYS`: **modo dev** (principal `dev`/`admin`) — só para desenvolvimento.
- Em produção, defina os tokens (papéis: `viewer` < `operator` < `admin`):

```bash
export ASO_API_KEYS='{"TOKEN_ADMIN":{"actor":"alice","role":"admin"},"TOKEN_OP":{"actor":"bob","role":"operator"}}'
curl -H "Authorization: Bearer TOKEN_OP" http://localhost:8000/v1/orchestrations
```

- Leitura (GET) exige `viewer`; escrita exige `operator`; ações críticas (aprovar/rejeitar
  aprovação, rollback, arquivar/restaurar projeto) exigem `admin`. O ator autenticado é
  registrado (ex.: `approved_by` e `ProjectEvent.actor`).
- Públicos (sem token): `/health`, `/metrics`, `/`, `/ui`, `/docs`, `/openapi.json`.

## Execução com agentes CLI reais (MVP-3)

Para executar um agente CLI real (ex.: Claude Code, Codex) em worktree isolado por card:

```bash
export ASO_TARGET_REPO=/caminho/do/repositorio-git      # repo onde os agentes trabalham
export ASO_CLI_COMMAND="claude -p"                       # comando do agente CLI
```

Cada card roda numa branch/worktree própria; o diff é coletado antes de qualquer merge e a
branch principal permanece intacta (§26A.6). Sem essas variáveis, usa-se o provider mock
(determinístico).

### Branches criadas pelo runtime

A branch sai do **título do card**
([ADR-0014](adrs/ADR-0014-agente-por-etapa-e-nomes-semanticos.md)):
`feat/calculadora-basica-a1b2c3d4` — prefixo Conventional Commits pelo tipo do card, slug
do título e sufixo curto de unicidade (obrigatório: `retry` e candidatos concorrentes
criam branches simultâneas para o mesmo card). O diretório do worktree fica em
`.aso/worktrees/<nome-achatado>` dentro do repositório-alvo.

Não há mais o prefixo `aso/`: as branches do runtime **não são distinguíveis por glob**
das branches humanas. Para saber quais são dele, consulte `card.branch` no banco:

```sql
select id, title, branch from kanban_cards where branch is not null;
```

Quem escolhe o agente de cada etapa é `agent_assignments` (F1..F7 + `naming`), na tela de
detalhe → ⚙ Config → "Agente por etapa", ou via
`PUT /v1/orchestrations/{id}/agents/{key}`. Sem escolha por etapa, vale o padrão da
orquestração. O agente `naming` é opcional — sem ele o nome sai do título do card, sem
custo; com ele, qualquer falha cai no nome determinístico e registra `NamingFallback`.

### Permissão de escrita do agente CLI (causa nº 1 de "diff vazio")

Em modo não-interativo, os CLIs **não escrevem arquivos por padrão** — não têm como pedir
aprovação, então respondem em texto, saem com código 0 e deixam o worktree intacto. O ASO
detecta o diff vazio, tenta de novo e marca o card como `Failed`. O comando do executor
precisa conceder a permissão explicitamente:

| Agente | Comando mínimo que escreve |
|---|---|
| Claude Code | `claude -p --permission-mode acceptEdits` (edita arquivos) |
| Claude Code | `claude -p --dangerously-skip-permissions` (edita **e** roda comandos) |
| Codex | `codex exec --sandbox workspace-write` (já embutido nos perfis gerenciados) |

Com `acceptEdits` o agente altera arquivos mas **não executa comandos** — cards que precisem
rodar build/testes travam nesse ponto. Conceder autonomia total é defensável aqui porque a
contenção do ASO é o **worktree isolado** + diff coletado + merge governado com CI e revisão
(regra 5 · [ADR-0009](adrs/ADR-0009-entrega-de-codigo-governada.md)), não a permissão do CLI.

Para corrigir um catálogo já existente: [`scripts/fix-executor-permissions.sh`](../scripts/fix-executor-permissions.sh)
(aceita `ASO_CLAUDE_PERMISSION_FLAG` para escolher a flag). Quando o card falha assim, o
motivo registrado passa a incluir **a última fala do agente** e o "Próximo passo" mostra o
bloqueio `executor_sem_permissao` com a orientação.

### Ver o que o agente está fazendo (streaming)

A tela de detalhe tem um painel "O que o agente está fazendo" que preenche em tempo real
([ADR-0015](adrs/ADR-0015-observabilidade-ao-vivo-da-execucao.md)). O ASO lê os pipes do
agente linha a linha, mas **a riqueza do que aparece depende do CLI**: em modo
não-interativo, `claude -p` imprime apenas a resposta final. Para ver ferramenta por
ferramenta, o CLI precisa emitir NDJSON:

| Agente | Flag que produz narração |
|---|---|
| Claude Code | `--output-format stream-json --verbose` |
| Codex | `--json` |

```bash
./scripts/enable-agent-stream.sh        # acrescenta as flags ao catálogo (idempotente)
./scripts/enable-agent-stream.sh --off  # remove
./scripts/manager.sh reiniciar          # necessário: o catálogo é lido no boot
```

O script usa a API quando ela está no ar e edita `.aso/executors.json` quando não está.
Sem as flags nada quebra — o painel cai no modo bruto e mostra as linhas como vierem.

Limites a conhecer:

- O log fica **em memória**: 2 000 linhas por orquestração, e **não sobrevive a restart da
  API**. É telemetria de acompanhamento; o que precisa durar (falha, motivo, diff) fica no
  event log e no `block_reason` do card.
- `ASO_AGENT_TIMEOUT` (default `1800`, em segundos) encerra um agente travado. Antes não
  havia limite nenhum: um CLI parado esperando permissão prendia uma thread do servidor e
  um worktree para sempre.
- Sem TTY, alguns CLIs bufferizam a saída em blocos de 4-8 KB por decisão própria. O NDJSON
  resolve isso para Claude e Codex; para outros agentes o "ao vivo" pode sair em rajadas.

### Catálogo Codex compatível com a conta

`./scripts/manager.sh seed` consulta `codex app-server`/`model/list` pelo processo da API e
sincroniza somente os modelos disponíveis na autenticação atual. O perfil `codex-default`
não fixa `-m` e ignora apenas o `config.toml` pessoal, evitando que ele force um modelo
incompatível; a autenticação ChatGPT é preservada. Perfis personalizados e Claude não são
alterados. Use `ASO_CODEX_BIN` quando o binário correto não for o primeiro `codex` do `PATH`.

O ASO recusa perfis indisponíveis antes de criar worktree. Também recusa servidores e
watchers (`npm run dev`, `--watch`) como quality gate: configure um comando finito, como
`npm test` ou `npm run build`. Em uma orquestração `created`/`blocked`, corrija pelo detalhe
ou por `PATCH /v1/orchestrations/{id}/execution-settings` e repita somente o docs-first.
Se uma tentativa anterior deixou apenas o scaffold de segurança, o retry reconhece que o
workspace ainda não tem código e completa o template determinístico, sem pedir ao agente que
invente fatos nem tratar o diff vazio como perda da orquestração.

## Observabilidade

- Eventos de domínio no `EventLog`: `OrchestrationCreated`, `ContextPatchApplied`,
  `QualityGateEvaluated`, `SnapshotCreated`, `ConflictRaised`, `CardMoved`, `AgentRun*`.
- Timeline por orquestração: `GET /v1/orchestrations/{id}/timeline` ou `aso timeline <id>`.
- **Métricas Prometheus** em `GET /metrics` (formato de exposição text/plain): `aso_orchestrations_total`,
  `aso_cards{status=...}`, `aso_open_conflicts_total`, `aso_adrs_total`, `aso_snapshots_total`.
- Auditoria: `GET /v1/orchestrations/{id}/audit` (eventos + patches aplicados/rejeitados + conflitos + approvals).

## Incidentes (básico)

1. Identificar a orquestração afetada (timeline, logs).
2. Verificar conflitos abertos e cards em `Blocked`/`Failed`.
3. Se estado inconsistente: restaurar o último snapshot estável (SnapshotEngine) e registrar ADR de rollback.
4. Registrar postmortem e converter em card de melhoria/tech-debt.
