# SPEC — Estrutura base do projeto Python + tooling

- **Card:** TASK-01
- **Épico:** EPIC-1 (Fundação do projeto)
- **Fase:** F5
- **ADRs:** ADR-0001, ADR-0004
- **Requisitos:** §37, §39, §40 Task 1
- **Depende de:** —

## Objetivo

Estabelecer a fundação técnica do ASO Runtime: o layout de código `src/aso/` que materializa o Modular Monolith + Clean/Hexagonal (ADR-0001), o empacotamento `pyproject.toml` e o tooling de qualidade (ruff, mypy, pytest). Sem essa base, nenhuma outra task pode ser implementada, testada ou validada.

Esta feature entrega um repositório instalável, com ambiente de desenvolvimento reproduzível (Docker Compose subindo Postgres 16) e pipelines locais de lint/type-check/test funcionando, alinhado à stack locked em ADR-0004. A estrutura de repositório do §37 (baseada em TS/monorepo) foi superada por ADR-0004; vale o layout Python de F2.

## Escopo

- Incluído:
  - `pyproject.toml` com metadados, dependências (fastapi, uvicorn, pydantic v2, sqlalchemy 2.x, alembic, typer, httpx, psycopg) e dev-deps (pytest, pytest-asyncio, coverage, ruff, mypy).
  - Layout `src/` com pacotes `src/aso/{control,kanban,agents,execution,governance,observability,shared,api,cli,db}`, cada um com `__init__.py`.
  - Configuração de ruff (lint+format), mypy (strict razoável) e pytest (pytest-asyncio, testpaths `tests/`).
  - `docker-compose.yml` subindo PostgreSQL 16 com volume persistente.
  - `.env.example`, `.gitignore`, `README.md` mínimo de setup, estrutura `tests/{unit,integration}`.
  - Alembic inicializado (`alembic.ini` + `migrations/env.py`) apontando para a URL do Postgres.
- Fora de escopo (MVP-1):
  - CI/CD remoto (GitHub Actions/GitLab); apenas comandos locais.
  - Frontend/web (diferido — F2 §54).
  - Publicação em índice de pacotes.

## Comportamento esperado

- Instalação via `pip install -e .` (ou `uv`) deixa o pacote `aso` importável e o entrypoint da CLI (`aso`) disponível.
- `ruff check` e `ruff format --check` rodam sem erros no esqueleto inicial.
- `mypy src/aso` roda sem erros no esqueleto inicial.
- `pytest` executa (mesmo que com testes-placeholder) e retorna sucesso.
- `docker compose up -d` sobe Postgres acessível na URL de `.env`; `alembic upgrade head` conecta com sucesso.
- Regra de dependência (Clean Architecture): módulos de domínio não importam de `api`/`cli`/`db`. O esqueleto deve refletir isso (sem imports invertidos).

## Contratos / Interfaces

```
src/aso/
  control/      kanban/      agents/      execution/
  governance/   observability/            shared/
  api/          cli/         db/
tests/
  unit/  integration/
pyproject.toml   docker-compose.yml   alembic.ini   migrations/
```

- Entrypoint CLI (console_script): `aso = "aso.cli.main:app"` (Typer app — detalhado em [cli-minimal.md](cli-minimal.md)).
- Entrypoint API (ASGI): `aso.api.main:app` (FastAPI — detalhado em [api-minimal.md](api-minimal.md)).
- Configuração central em `src/aso/shared/config.py` (Pydantic `Settings`, lê `DATABASE_URL` e demais env vars).

## Critérios de aceite

- [ ] Projeto instala (`pip install -e .`) e importa `import aso` sem erro.
- [ ] `ruff`, `mypy` e `pytest` configurados e executando com sucesso no esqueleto.
- [ ] `docker compose up` sobe Postgres 16 e a aplicação conecta via `DATABASE_URL`.
- [ ] Layout `src/aso/{control,kanban,agents,execution,governance,observability,shared,api,cli,db}` presente.
- [ ] Alembic inicializado e `alembic upgrade head` executa contra o Postgres do compose.

## Rastreabilidade

§37/§39/§40 Task 1 → ADR-0001, ADR-0004 → esta spec → TASK-01 → `src/aso/` (esqueleto), `pyproject.toml`, `docker-compose.yml`, `src/aso/shared/config.py` → `tests/unit/test_project_layout.py`
