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

Cada card roda numa branch/worktree `aso/<agente>-<id>`; o diff é coletado antes de qualquer
merge e a branch principal permanece intacta (§26A.6). Sem essas variáveis, usa-se o provider
mock (determinístico).

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
