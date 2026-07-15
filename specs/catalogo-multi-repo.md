# SPEC — Catálogo multi-repo governado

- **Card:** TASK-84
- **Épico:** EPIC-2 / EPIC-7
- **Fase:** F5/F7
- **ADRs:** ADR-0006, ADR-0008, ADR-0010
- **Depende de:** TASK-79, TASK-82, TASK-83

## Objetivo

Persistir projetos como catálogo relacional auditável, associar várias orquestrações a um
workspace canônico e substituir deleção destrutiva por arquivamento.

## Escopo

- Porta `ProjectRepository` e adapters in-memory/SQLAlchemy.
- Tabelas `projects` e `project_events`; FKs restritivas e backfill legado.
- CRUD HTTP com `PATCH`/alias `PUT`, arquivamento/restauração e histórico.
- Filtro de orquestrações por projeto e snapshot de workspace na criação.
- Console de catálogo e fluxo de criação com pré-análise/docs-first.
- Compatibilidade de orquestrações sem projeto.

## Fora de escopo

- Hard delete de projeto ou orquestração.
- Alteração retroativa do workspace de orquestrações existentes.
- Clonagem remota de repositórios e sincronização com provedores Git.

## Contratos

- `target_path` de projeto novo é obrigatório, canônico e único inclusive se arquivado.
- Projeto arquivado fica oculto por padrão e rejeita novas orquestrações.
- Path divergente com `project_id` retorna conflito; path do projeto é copiado para a nova
  orquestração.
- Arquivar/restaurar exige `admin`; criar/editar exige `operator`; ler exige `viewer`.
- Toda mutação de projeto registra `ProjectEvent` com ator, `before` e `after`.

## Critérios de aceite

- [x] Persistência sobrevive a reinício e mantém eventos.
- [x] FKs impedem remoção de projeto referenciado.
- [x] Migração preserva IDs legados e neutraliza paths conflitantes.
- [x] Arquivamento preserva cards, ADRs, snapshots e eventos.
- [x] Console não cria orquestração descartável nem inicia Autopilot implicitamente.
- [x] OpenAPI e documentação docs-first refletem o contrato.

## Rastreabilidade

ADR-0006/0008 → ADR-0010 → esta spec → TASK-84 → `project_service.py`, portas/adapters,
migration, API e console → testes `test_project_*`/`test_projects_*`.
