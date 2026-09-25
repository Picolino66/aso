# ASO Runtime — Documentação

Documentação canônica (fonte de verdade para agentes) do **ASO Runtime — Autonomous Software Orchestrator Runtime**.

Todo conteúdo é mantido em **português do Brasil (pt-BR)**.

## Visão rápida

- **Stack:** Python (ver ADR-0004) · API v1 (auth/RBAC) + console em `/ui` + CLI
- **Código:** `src/aso/` · persistência relacional (Alembic) · CI + smoke Docker · métricas/SLOs
- **Rodar em Docker:** `docker compose up --build` → API em `http://localhost:8000` (UI em `/ui`, docs em `/docs`)
- **Estado do backlog de melhorias:** [`tasks/README.md`](../tasks/README.md) e
  [`tasks/EXECUTION_STATE.md`](../tasks/EXECUTION_STATE.md)

> Os marcadores "F1–F7 concluída" e "snapshot O7" que ficavam aqui descreviam o **processo de
> construção do próprio ASO** (artefatos mantidos à mão em `.aso/`), não o estado do runtime.

## Índice

### Comece aqui
- [Como o ASO funciona (glossário e fluxo)](HOW_IT_WORKS.md)

### Governança e contexto
- Regras invioláveis → código → teste: [GOVERNANCE.md](GOVERNANCE.md)
- Contexto canônico: [`.aso/context/orchestrator-context.json`](../.aso/context/orchestrator-context.json)
- Snapshots: [`.aso/snapshots/`](../.aso/snapshots/)
- Quality gates: [`.aso/quality-gates/`](../.aso/quality-gates/)

### Fases
- [F1 — Discovery & Strategy](phases/F1-discovery.md) ✅
- [F2 — Architecture & Design](phases/F2-architecture.md) ✅
- [F3 — Data & API Contracts](phases/F3-contracts.md) ✅
- [F4 — UX/UI & Planning](phases/F4-planning.md) ✅
- [F5 — Engineering Execution](phases/F5-execution.md) ✅ *(MVP-1 completo; 15/15 cards)*
- [F6 — Quality, Docs & Deploy](phases/F6-quality.md) ✅ *(CI/CD, segurança, docs, deploy/rollback)*
- [F7 — Operate & Evolve](phases/F7-operate.md) ✅ *(observabilidade, SLOs, feedback→backlog)*

### Documentação técnica
- [Requisitos (resumo)](requirements.md) · [Requisitos completos](../requerimentos.md)
- [Arquitetura](architecture.md) · [Modelo de domínio](domain-model.md) · [API](api.md) · [`contracts/openapi.json`](../contracts/openapi.json) (gerado, ADR-0064)
- [Módulo de projetos](modules/projetos/index.md) · [Executores](modules/executores/index.md) · [Fluxo do console](modules/console/index.md)
- [Kanban](kanban.md) · [Agentes](agents.md) · [Contexto](context.md) · [Quality Gates](quality-gates.md) · [Snapshots](snapshots.md)
- [Operações (runbook)](operations.md) · [Deploy & Rollback](deploy.md) · [CHANGELOG](../CHANGELOG.md)
- [MVP-1](mvp/mvp-1.md)
- [Plano de fidelidade ao fluxo/wireframe](plano-fidelidade-fluxo.md) — diagnóstico ≈55% e backlog FID-01…FID-27
- [Design system (`/ui/*`)](design-system.md) · [Mapa de páginas e rotas](mapa-paginas.md)

### Estrutura agentic
- [`specs/`](../specs/README.md) · [`tasks/`](../tasks/README.md) · [`agents/`](../agents/README.md) · [`skills/`](../skills/README.md)

### ADRs
- [ADR-0001 — Arquitetura do runtime: Modular Monolith + Hexagonal](adrs/ADR-0001-runtime-architecture.md)
- [ADR-0002 — Kanban como plano de execução](adrs/ADR-0002-kanban-as-execution-plane.md)
- [ADR-0003 — ContextBus como governança soberana do contexto](adrs/ADR-0003-contextbus-governance.md)
- [ADR-0004 — Stack de implementação: Python](adrs/ADR-0004-tech-stack-python.md)
- [ADR-0005 — Consistência de dados e versionamento de API](adrs/ADR-0005-data-consistency-and-api-versioning.md)
- [ADR-0006 — Persistência via repository ports + adapters (SQLAlchemy)](adrs/ADR-0006-persistence-repository-adapters.md)
- [ADR-0007 — Provedor LLM injetável e planejamento por LLM (autopilot)](adrs/ADR-0007-llm-provider-and-autopilot.md)
- [ADR-0008 — Workspace por orquestração e documentação docs-first](adrs/ADR-0008-workspace-por-orquestracao.md)
- [ADR-0009 — Entrega de código somente com evidência verificável](adrs/ADR-0009-entrega-de-codigo-governada.md)
- [ADR-0010 — Catálogo multi-repo relacional e arquivamento governado](adrs/ADR-0010-catalogo-multi-repo-governado.md)
- [ADR-0011 — Descoberta de capacidades de executores CLI](adrs/ADR-0011-descoberta-de-capacidades-cli.md)
- [ADR-0012 — Drift-check contínuo de docs-first + self-heal (F5/F6)](adrs/ADR-0012-drift-check-docs-first.md)
- [ADR-0013 — Tela de detalhe orientada a "próximo passo" + motor no runtime](adrs/ADR-0013-tela-de-detalhe-por-proximo-passo.md)
- [ADR-0014 — Executor por etapa da esteira e nomes de branch derivados do card](adrs/ADR-0014-agente-por-etapa-e-nomes-semanticos.md)
- [ADR-0015 — Observabilidade ao vivo da execução e esteira legível](adrs/ADR-0015-observabilidade-ao-vivo-da-execucao.md)
- [ADR-0016 — Ficha da demanda (triagem) alimentando o motor de decisão](adrs/ADR-0016-ficha-da-demanda.md)
- [ADR-0017 — Revisão independente de código (§14/§15)](adrs/ADR-0017-revisao-independente-de-codigo.md)
- [ADR-0018 — Kanban fiel: colunas restantes e ativação de dependencies/blocked_by](adrs/ADR-0018-kanban-fiel-colunas-e-dependencias.md)
- [ADR-0019 — Roteamento de falha](adrs/ADR-0019-roteamento-de-falha.md)
- [ADR-0020 — Discovery e aprovação](adrs/ADR-0020-discovery-e-aprovacao.md)
- [ADR-0021 — Especificação e revisão documental](adrs/ADR-0021-especificacao-e-revisao-documental.md)
- [ADR-0022 — Bateria de validações e escolha automática de esforço](adrs/ADR-0022-bateria-de-validacoes-e-effort-automatico.md)
- [ADR-0023 — Implantação governada (§18-22, "Incremento F")](adrs/ADR-0023-implantacao-governada.md)
- [ADR-0024 — Corrida de candidatos: causa raiz do candidato fantasma](adrs/ADR-0024-corrida-de-candidatos-broken-pipe.md)
- [ADR-0025 — QA humano, hierarquia de cards e aprendizado da esteira](adrs/ADR-0025-qa-hierarquia-aprendizado.md)
- [ADR-0026 — Custo real do agente e orçamento com freio](adrs/ADR-0026-custo-real-e-orcamento.md)
- [ADR-0027 — Sobrevivência a crash de processo](adrs/ADR-0027-sobrevivencia-a-crash.md)
- [ADR-0028 — Regras de roteamento (RoutingRule)](adrs/ADR-0028-regras-de-roteamento.md)
- [ADR-0029 — Pipeline de implantação multi-estágio (Environment)](adrs/ADR-0029-pipeline-de-implantacao.md)
- [ADR-0030 — Checklist de preparação e tarefa vinculada por dependência](adrs/ADR-0030-checklist-de-preparacao.md)
- [ADR-0031 — Limite de tentativas por card e correção do contador](adrs/ADR-0031-limite-de-tentativas.md)
- [ADR-0032 — Incident como entidade de primeira classe](adrs/ADR-0032-incidente-de-primeira-classe.md)
- [ADR-0033 — Comentário de revisão ancorado em arquivo/linha (wf §20.3)](adrs/ADR-0033-comentario-de-revisao-ancorado.md)
- [ADR-0034 — Design system wireframe: tokens, tema claro e componentes reutilizáveis](adrs/ADR-0034-design-system-wireframe.md)
- [ADR-0035 — Header compartilhado com os 9 elementos da spec](adrs/ADR-0035-header-compartilhado.md)
- [ADR-0036 — Sidebar de 16 seções e mapa de páginas](adrs/ADR-0036-sidebar-e-mapa-de-paginas.md)
- [ADR-0037 — Dashboard operacional (Tela 01)](adrs/ADR-0037-dashboard-operacional.md)
- [ADR-0038 — Lista de demandas com filtros e ações (Tela 02)](adrs/ADR-0038-lista-de-demandas.md)
- [ADR-0039 — Cadastro de demanda completo (Tela 03)](adrs/ADR-0039-cadastro-de-demanda-completo.md)
- [ADR-0040 — Estrutura da demanda em árvore (Tela 10)](adrs/ADR-0040-estrutura-da-demanda-em-arvore.md)
- [ADR-0041 — Detalhes do card em dez abas (Tela 12)](adrs/ADR-0041-detalhes-do-card-em-dez-abas.md)
- [ADR-0042 — Editor visual de regras de roteamento (Tela 31)](adrs/ADR-0042-editor-visual-de-regras-de-roteamento.md)
- [ADR-0043 — Detalhes da demanda em 11 abas (Tela 04)](adrs/ADR-0043-detalhes-da-demanda-em-onze-abas.md)
- [ADR-0044 — Classificação editável e painel de recomendação (Telas 05 e 13)](adrs/ADR-0044-classificacao-editavel-e-recomendacao.md)
- [ADR-0045 — Discovery técnico e sua aprovação (Telas 06 e 07)](adrs/ADR-0045-discovery-tecnico-e-aprovacao.md)
- [ADR-0046 — Documentos, especificações e revisão documental (Telas 08 e 09)](adrs/ADR-0046-documentos-e-revisao-documental.md)
- [ADR-0047 — Kanban operacional completo (Tela 11)](adrs/ADR-0047-kanban-operacional-completo.md)
- [ADR-0048 — Execução, quality gates e tratamento de falhas (Telas 15, 16 e 17)](adrs/ADR-0048-execucao-quality-gates-e-falhas.md)
- [ADR-0049 — Code review, correção obrigatória, testes manuais e registro de bug (Telas 18, 19, 20 e 21)](adrs/ADR-0049-code-review-testes-manuais-e-bugs.md)
- [ADR-0050 — Aprovação, pipeline, validação, rollback, aceite e encerramento (Telas 22-27)](adrs/ADR-0050-implantacao-validacao-rollback-aceite-encerramento.md)
- [ADR-0051 — Auditoria cross-demanda com filtros (Tela 28)](adrs/ADR-0051-auditoria-com-filtros.md)
- [ADR-0052 — Métricas e aprendizado com recorte por projeto e período (Tela 29)](adrs/ADR-0052-metricas-e-aprendizado.md)
- [ADR-0053 — Catálogo de agentes como fonte de verdade de permissões (Tela 30)](adrs/ADR-0053-catalogo-de-agentes.md)
- [ADR-0054 — Requisitos de UX obrigatórios aplicados transversalmente (Tela 39)](adrs/ADR-0054-requisitos-ux-transversais.md)
- [ADR-0055 — Correções do code-review ultra (6 bugs reais pós-FID-27)](adrs/ADR-0055-correcoes-do-code-review-ultra.md)
- [ADR-0056 — CI executada × CI declarada](adrs/ADR-0056-ci-executada-e-declarada.md)
- [ADR-0057 — Segurança por padrão: modelo de ameaça local e papéis para comandos no host](adrs/ADR-0057-seguranca-por-padrao.md)
- [ADR-0058 — Claim atômico (lease) de execução do card](adrs/ADR-0058-claim-de-execucao-do-card.md)
- [ADR-0059 — Contrato `TaskEnvelope` versionado entre runtime e agentes CLI](adrs/ADR-0059-contrato-task-envelope.md)
- [ADR-0060 — Quality gate escopado por fase e status `SKIPPED`](adrs/ADR-0060-gate-escopado-por-fase.md)
- [ADR-0061 — Congelamento de seções por snapshot (reafirma ADR-0003) e `restaurar_ledger`](adrs/ADR-0061-congelamento-de-snapshot.md)
- [ADR-0062 — Docs-first e self-heal via entrega governada](adrs/ADR-0062-docs-first-via-entrega-governada.md)
- [ADR-0063 — OrchestratorContext como memória de trabalho via ContextBuilder](adrs/ADR-0063-context-builder.md)
- [ADR-0064 — Contrato OpenAPI gerado do código](adrs/ADR-0064-openapi-gerado-do-codigo.md)
- [ADR-0065 — Registro persistido de execuções de agente (`agent_runs`)](adrs/ADR-0065-registro-de-execucoes-agent-runs.md)
- [ADR-0066 — Camada de aplicação por caso de uso (extração incremental do `OrchestrationService`)](adrs/ADR-0066-camada-de-aplicacao.md)
- [ADR-0067 — Execução assíncrona: fila persistida de jobs e workers no processo](adrs/ADR-0067-execucao-assincrona-com-fila.md)
- [ADR-0068 — Gravação incremental, versão otimista e cache de agregados com descarte](adrs/ADR-0068-gravacao-incremental-e-versao-otimista.md)
- [ADR-0069 — Leitura somente do repositório por agentes de pergunta (discovery e revisão)](adrs/ADR-0069-leitura-do-repositorio-por-agentes-de-pergunta.md)
- [ADR-0070 — Uso e custo de todos os executores (fontes e tabela de preços)](adrs/ADR-0070-uso-e-custo-de-todos-os-executores.md)
- [ADR-0071 — Retry único: o roteamento de falha é a única camada de nova tentativa](adrs/ADR-0071-retry-unico-pelo-roteamento-de-falha.md)
- [ADR-0072 — Respostas das funções de agente com JSON Schema gerado dos modelos](adrs/ADR-0072-respostas-estruturadas-json-schema.md)
- [ADR-0073 — Esforço (effort) mapeado por tipo de executor](adrs/ADR-0073-effort-mapeado-por-executor.md)
- [ADR-0074 — Execução em lote por ondas com limite de paralelismo por orquestração](adrs/ADR-0074-paralelismo-por-onda.md)
- [ADR-0075 — Remoção de código morto e de abstrações que não mudavam a execução](adrs/ADR-0075-remocao-de-codigo-morto.md)
- [ADR-0076 — Catálogo único de executores (e flags como campo do perfil)](adrs/ADR-0076-catalogo-unico-de-executores.md)
- [ADR-0077 — Índice estrutural do repositório por commit (e por que não embeddings)](adrs/ADR-0077-indice-estrutural-por-commit.md)
- [ADR-0078 — Consolidação do console: uma geração de páginas, uma navegação](adrs/ADR-0078-consolidacao-do-console.md)
