# SPEC — Persistência (repository ports + adapters)

- **Card:** TASK-16
- **Épico:** EPIC-6 (Governança) / infraestrutura
- **Fase:** F5 (incremento pós-O5)
- **ADRs:** ADR-0001, ADR-0005, ADR-0006
- **Requisitos:** §29, §26A.10 (concorrência futura), §43 (mock antes de real)
- **Depende de:** TASK-03 (contexto), TASK-04 (kanban), TASK-10/11/12 (governança)

## Objetivo

Persistir o aggregate de uma orquestração para que o estado sobreviva entre execuções, mantendo a arquitetura hexagonal: o domínio depende de uma porta `OrchestrationRepository`, e os adapters concretos (in-memory, SQLAlchemy) ficam na borda.

## Escopo

- Incluído: porta de repositório; estado serializável `OrchestrationState`; adapter in-memory; adapter SQLAlchemy **normalizado** (§29) com **tabelas de junção** (card_links, adr_links, board_columns, planned_agents, adr_options, gate_criteria, value_items), **índices** e **consultas** (por status, links reversos); PK composta em `adrs`; contexto em JSONB; reidratação do aggregate; composition root via `ASO_DATABASE_URL`; **migrations Alembic** (revisão inicial única, `alembic check` limpo); validado no PostgreSQL via `docker compose`.
- Fora de escopo (futuro): pooling/concorrência multi-writer; cache de leitura; normalizar payloads livres e sublistas pros/cons (JSON).

## Comportamento esperado

- Toda mutação relevante (`create_orchestration`, `run_card`, `run_quality_gate`) persiste o aggregate.
- Leitura de uma orquestração não em cache carrega do repositório e reidrata os serviços de domínio.
- SQLite em dev/testes; Postgres (JSONB) em produção — mesmos modelos.

## Contratos / Interfaces

- `aso.persistence.ports.OrchestrationRepository`: `save(state)`, `load(id) -> state | None`, `list_ids()`.
- `aso.persistence.state.OrchestrationState` (Pydantic): orchestration, plan, contexto (payload/version/frozen/history), adrs, snapshots, conflicts, board, cards, card_events, events.
- `aso.persistence.memory.InMemoryOrchestrationRepository`.
- `aso.db.repository.SqlAlchemyOrchestrationRepository(url)`.
- `aso.bootstrap.build_service()`.

## Critérios de aceite

- [x] Domínio depende apenas da porta (sem import de SQLAlchemy em `control`).
- [x] Estado sobrevive a uma nova instância do serviço sobre o mesmo banco.
- [x] SQLite nos testes sem exigir Postgres.
- [x] JSONB no Postgres via variant.
- [x] `ASO_DATABASE_URL` seleciona o adapter no composition root.
- [x] Tabelas normalizadas por entidade (§29); `alembic upgrade head` provisiona o schema.
- [x] `alembic check` confirma schema idêntico aos modelos ORM.

## Rastreabilidade

§29/ADR-0005 → ADR-0006 → esta spec → TASK-16 → `aso/persistence/*`, `aso/db/*`, `aso/bootstrap.py` → `tests/integration/test_persistence.py`
