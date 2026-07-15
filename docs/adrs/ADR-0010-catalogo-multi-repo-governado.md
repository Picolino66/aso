# ADR-0010 — Catálogo multi-repo relacional e arquivamento governado

- **Status:** ACCEPTED
- **Fase:** F5/F7 (evolução pós-O7)
- **Data:** 2026-07-14
- **Relaciona-se com:** [ADR-0006](ADR-0006-persistence-repository-adapters.md)
  (portas e persistência relacional),
  [ADR-0008](ADR-0008-workspace-por-orquestracao.md) (workspace por orquestração) e
  [ADR-0009](ADR-0009-entrega-de-codigo-governada.md) (execução verificável)
- **Supersede parcialmente:** a postergação do CRUD multi-repo na opção 3 da ADR-0008.

## Contexto

O incremento inicial de projetos usava `.aso/projects.json` e removia em cascata as
orquestrações vinculadas. Isso criava duas fontes de persistência, não sobrevivia de
forma uniforme ao deploy relacional e permitia destruir ADRs, cards, snapshots e eventos.
Também não definia como uma mudança de pasta afetaria execuções existentes.

O catálogo precisa agrupar várias orquestrações por repositório sem se tornar dono dos
agregados de governança. O `ContextBus` continua sendo o único escritor do contexto
canônico; metadados de catálogo têm ciclo de vida e auditoria próprios.

## Opções consideradas

1. **Manter JSON e deleção em cascata.** Simples, mas incompatível com a persistência
   transacional e com a retenção de auditoria.
2. **Tabela de projetos com hard delete restrito.** Evita cascata, porém perde o catálogo e
   dificulta reutilizar de modo inequívoco um path anterior.
3. **Agregado relacional independente com soft archive e eventos append-only.** Preserva
   histórico, suporta RBAC e mantém o vínculo sem acoplar ciclos de vida. Escolhida.

## Decisão

- `Project` contém `id`, `name`, `description`, `target_path`, `status`, timestamps e
  `archived_at`; novos projetos exigem path existente, absoluto, canônico e único,
  inclusive entre arquivados.
- Uma porta `ProjectRepository` possui adapters in-memory e SQLAlchemy. `projects` e
  `project_events` são tabelas relacionais; eventos registram ator e estados anterior e
  posterior para criação, atualização, arquivamento e restauração. Escritas com estado
  anterior usam controle otimista e rejeitam updates obsoletos.
- `orchestrations.project_id` e `boards.project_id` usam FKs `RESTRICT`. `DELETE` na API
  significa arquivar e requer `admin`; restauração também requer `admin` e pode receber um
  novo path. Não existe endpoint de hard delete de orquestração.
- Ao criar uma orquestração vinculada, o serviço exige projeto ativo e copia o path para
  `Orchestration.target_path`. A cópia é um snapshot operacional: editar ou arquivar o
  projeto só afeta novas orquestrações.
- Orquestrações sem projeto e `ASO_TARGET_REPO` como fallback continuam suportados.
- A migração cria projetos arquivados para IDs legados antes das FKs. Um path só é retido
  quando é inequívoco; conflitos ficam `NULL` até restauração administrativa.

## Trade-offs

- **+** Rastreabilidade e dados de execução sobrevivem ao arquivamento.
- **+** Unicidade do path evita duas identidades para o mesmo workspace.
- **+** O agregado de orquestração permanece executável sem depender do estado atual do
  catálogo.
- **−** Projetos arquivados retêm o path e precisam ser restaurados para reutilização.
- **−** O path é um snapshot por orquestração; migração de execuções existentes para outra
  pasta exige uma operação futura explícita, não uma edição implícita.

## Consequências

- A tela `/ui/` administra ativos/arquivados e expõe o Kanban agrupado por projeto.
- `/ui/nova` segue projeto → pré-análise → demanda/configuração → criação → docs-first →
  detalhe. Criar projeto não cria orquestração temporária nem toca o workspace.
- `ProjectEvent` não é um `ContextPatch`: ele audita somente o catálogo. Mudanças docs-first
  continuam passando pelo ContextBus conforme ADR-0008.
- Backups, retenção e consultas passam a cobrir `projects` e `project_events` junto das
  demais tabelas normalizadas.

## Evidências

- Spec: [`specs/catalogo-multi-repo.md`](../../specs/catalogo-multi-repo.md).
- Card: `TASK-84`.
- Testes: domínio/concorrência, adapters, migração, API/RBAC, FKs e regressão de retenção.
- Migration: `f84c2a1d9e30_projects_catalog.py`.
