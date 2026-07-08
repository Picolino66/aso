# ADR-0006 — Persistência via repository ports + adapters (SQLAlchemy)

- **Status:** ACCEPTED
- **Fase:** F5 (incremento pós-O5)
- **Criado por:** ArchitectureDesignAgent / DatabaseAgent
- **Revisado por:** ReviewAgent
- **Data:** 2026-07-02
- **Relaciona-se com:** [ADR-0001](ADR-0001-runtime-architecture.md) (hexagonal), [ADR-0005](ADR-0005-data-consistency-and-api-versioning.md) (Postgres/SQLAlchemy)
- **Override:** estende a seção `engineering` congelada em O5 (justificado por este ADR).

## Contexto

No MVP-1 o estado era in-memory: não sobrevivia entre execuções. É preciso persistir o aggregate da orquestração (contexto, cards, ADRs, snapshots, eventos) mantendo a arquitetura hexagonal (ADR-0001) e a decisão de banco (ADR-0005), sem exigir Postgres para rodar os testes.

## Opções consideradas

### 1. Normalizar já todas as tabelas §29
- **Prós:** modelo relacional completo, queries ricas.
- **Contras:** custo alto; prematuro antes de estabilizar o aggregate.

### 2. Repository port + adapter com aggregate serializado em JSON (escolhido)
- **Prós:** desacopla domínio da persistência (porta `OrchestrationRepository`); `OrchestratorContext` já é JSONB por ADR-0005; portabilidade SQLite (testes) / Postgres (produção) via SQLAlchemy; evolução para normalização é transparente ao domínio.
- **Contras:** consultas por campos internos exigem carregar o documento (aceitável no MVP).

### 3. Escrever direto com SQLAlchemy no serviço
- **Contras:** acopla domínio ao ORM; viola Ports & Adapters.

## Decisão

- Porta `OrchestrationRepository` (save/load/list_ids) em `aso/persistence/ports.py`.
- Estado serializável `OrchestrationState` (Pydantic) captura o aggregate completo.
- Adapters: `InMemoryOrchestrationRepository` (default/dev) e `SqlAlchemyOrchestrationRepository`.
- Uma linha por orquestração com o aggregate em coluna JSON — **JSONB no Postgres** via `JSON().with_variant(JSONB, "postgresql")`; JSON genérico no SQLite (testes).
- Composition root em `aso/bootstrap.py`: usa SQLAlchemy quando `ASO_DATABASE_URL` está definido, senão in-memory. Domínio depende só da porta.

## Trade-offs

- Coleções de valor (listas, mapas) ficam em colunas JSON dentro da tabela da própria entidade — pragmático e portável, em vez de tabelas de junção dedicadas.

## Consequências

- Estado sobrevive entre execuções (CLI/API) quando `ASO_DATABASE_URL` aponta para um banco.
- `OrchestrationService` recebe o repositório por injeção e reidrata o aggregate via métodos `hydrate` dos serviços de domínio.

## Atualização — normalização §29 + Alembic (implementado)

O adapter evoluiu de documento-único para **tabelas normalizadas** (§29): `orchestrations`, `orchestrator_contexts`, `context_history`, `execution_plans`, `boards`, `kanban_cards`, `card_events`, `adrs`, `snapshots`, `conflicts`, `events`. Cada entidade tem sua tabela com colunas escalares consultáveis; o payload do contexto permanece JSONB (ADR-0005).

- Escrita transacional: delete-and-reinsert dos filhos + `merge` do pai, com `flush()` por nível de FK (o Postgres enforce FKs).
- **Alembic** provê as migrations (`migrations/`); `alembic check` confirma que o schema é idêntico aos modelos ORM.
- Produção usa `alembic upgrade head` (repositório com `create_schema=False`); dev/testes usam `create_all` por conveniência.

## Atualização 2 — normalização estrita (tabelas de junção) + índices + consultas

Coleções de valor deixaram de ser colunas JSON e viraram **tabelas de junção**:
- `board_columns` (colunas do board), `planned_agents` (agentes do ExecutionPlan);
- `card_links` (rel = agents/dependencies/blocked_by/acceptance_criteria/linked_*) — uma linha por valor;
- `adr_links` (rel = tradeoffs/consequences/linked_cards/linked_requirements).

**Índices** adicionados: FKs `orchestration_id`, `ix_cards_orch_status`, `ix_adrs_orch_status`, `ix_card_links_card_rel`, `ix_card_links_orch_rel_value` (consulta reversa), `ix_events_orch_seq`, etc.

**Consultas** no adapter (fora da porta de escrita): `cards_by_status`, `count_cards_by_status`, `adrs_by_status`, `cards_linked_to_adr` (reversa via `card_links`).

## Atualização 3 — normalização total + PK composta de ADR

- `options_considered` → `adr_options`; critérios de gate → `gate_criteria`; demais listas planas (success_criteria, frozen_sections, ids de snapshot/conflict, blocking/warnings/required de gate) → tabela genérica `value_items` (owner_type/owner_id/rel/value). Restam em JSON apenas payloads (contexto/eventos/approval) e sublistas de opção (pros/cons).
- **PK composta `(orchestration_id, id)` em `adrs`**: o id de ADR é sequencial por orquestração (ADR-0001...), então o id sozinho colidia entre orquestrações no mesmo banco. `adr_links`/`adr_options` referenciam `adr_id` como referência leve.
- Migrations consolidadas em uma **revisão inicial única** (greenfield); `alembic upgrade head` + `alembic check` limpos. Validado end-to-end no PostgreSQL via `docker compose`.
