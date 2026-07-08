# ADR-0005 — Consistência de dados e versionamento de API

- **Status:** ACCEPTED
- **Fase:** F3
- **Criado por:** DataApiContractsAgent
- **Revisado por:** ReviewAgent · DatabaseAgent
- **Data:** 2026-07-02

## Contexto

O ASO Runtime precisa de garantias fortes sobre o contexto canônico (§17, §19): patches são aplicados por um único escritor (ContextBus, ADR-0003) e snapshots congelam seções. Também precisa de contratos de API estáveis para consumidores (UI, CLI, integrações).

## Opções consideradas

### Consistência
1. **Eventual** — bom para escala distribuída; ruim para o contexto soberano, que exige leitura-após-escrita e locks por `target_keys`.
2. **Forte (transacional, um Postgres)** — simples, consistente, compatível com ContextBus single-writer e monolito modular (ADR-0001).

### Versionamento de API
1. Sem versão — quebra consumidores a cada mudança.
2. **Prefixo de path `/v1`** — explícito, simples, alinhado ao princípio contrato-first.

## Decisão

- **Consistência forte**: uma instância PostgreSQL; `OrchestratorContext` versionado (coluna `version` incremental + histórico append-only); escrita serializada pelo ContextBus com locks por `target_keys`.
- **Versionamento de API por path** `/v1`; mudanças incompatíveis exigem `/v2` e atualização dos consumidores (§ regra "nunca quebrar contrato sem nova versão").
- **Idempotência** via header `Idempotency-Key` em POSTs de criação.
- **Migrations** versionadas com Alembic; nenhuma alteração de schema fora de migration.

## Trade-offs

- Consistência forte limita escala horizontal de escrita — aceitável no MVP (local-first); reavaliar em F7 se houver gargalo.

## Consequências

- `contracts.consistency_model = strong`.
- `contracts.api_version = v1`; OpenAPI em `contracts/openapi.yaml`.
- Toda entidade com `id` + timestamps; DTOs sem campos `any`/`object` sem descrição (gate F3).
