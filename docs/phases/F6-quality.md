# F6 — Quality, Docs & Deploy — ASO Runtime

> Fase F6. Depende de O5. Estado: **F6 concluída — snapshot O6 gerado** (aguardando aprovação humana).

## 1. CI/CD (TASK-19)

Pipeline GitHub Actions ([.github/workflows/ci.yml](../../.github/workflows/ci.yml)) executa, em push/PR:
`ruff check` + `ruff format --check` → `mypy src` → `pytest --cov-fail-under=80` → `alembic upgrade head` + `alembic check` → `bandit` (SAST) → `pip-audit` (SCA).

Todos os passos validados localmente: 55 testes, cobertura **98,1%**, ruff/mypy limpos, alembic check limpo.

## 2. Segurança (TASK-20)

- **SAST (bandit):** 0 apontamentos em `src`.
- **SCA (pip-audit):** sem vulnerabilidades conhecidas.
- Secrets só por env; deny-by-default no ContextBus; aprovação humana para ações críticas (evolui no MVP-2).

## 3. Documentação & Deploy (TASK-21)

- [operations.md](../operations.md) — runbook (executar, banco, migrations, gates, observabilidade, incidentes).
- [deploy.md](../deploy.md) — plano de deploy + **rollback** (imagem anterior, `alembic downgrade`, restore de snapshot, restore de backup).
- [Dockerfile](../../Dockerfile) + [docker-entrypoint.sh](../../docker-entrypoint.sh) — imagem que migra e sobe a API.
- [CHANGELOG.md](../../CHANGELOG.md).

## 4. Quality Gate F6 → F7

| Critério | Status | Evidência |
|---|---|---|
| Security scan sem críticos/altos | ✅ PASSED | bandit 0; pip-audit sem vulnerabilidades |
| Testes dos fluxos críticos | ✅ PASSED | 55 testes (unit+integração+API+CLI+persistência) |
| Documentação técnica completa | ✅ PASSED | /docs (fases, api, domínio, operations, deploy) |
| `/docs/index.md` sem links quebrados | ✅ PASSED | índice atualizado |
| Runbooks de operação/incidente | ✅ PASSED | operations.md |
| Deploy com rollback testado | ⚠️ PARCIAL | plano + Dockerfile; deploy real fora do escopo MVP (§7) |
| Pipeline CI/CD verde | ✅ PASSED | passos validados localmente (idênticos ao ci.yml) |

**Resultado: PASSED (1 warning: deploy real diferido por escopo §7) → snapshot O6 gerado.**
