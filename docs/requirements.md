# Requisitos — ASO Runtime

> Resumo executivo dos requisitos. **Fonte completa e canônica:** [`requerimentos.md`](../requerimentos.md).
> Consolidação de discovery: [F1 — Discovery & Strategy](phases/F1-discovery.md).

## 1. Visão

**ASO Runtime — Autonomous Software Orchestrator Runtime** é um runtime multiagente de engenharia de software com Kanban operacional que decompõe demandas, distribui tarefas entre agentes especializados, executa em paralelo com isolamento, valida por quality gates, registra ADRs, gera snapshots e conduz o ciclo completo da ideia à produção (fases F1–F7).

**Personas:** Tech Lead / Dev sênior orquestrador; Engenheiro de Plataforma / Arquiteto; Product/Engineering Manager agentic (ver [F1 §3](phases/F1-discovery.md)).

## 2. Problema

Ferramentas de agentes de código implementam tarefas mas não preservam contexto global, não respeitam decisões arquiteturais, geram conflitos entre agentes paralelos e não oferecem rastreabilidade requisito → decisão → task → código → teste → deploy nem quality gates que bloqueiem avanço inconsistente.

## 3. Escopo (incluído)

- Multiagentes em multitarefas com isolamento e controle central.
- Quadro Kanban como mecanismo de controle operacional (plano de execução).
- Orquestração ponta a ponta F1–F7.
- Governança: contexto canônico soberano, ADRs, quality gates, snapshots e aprovações humanas.
- Configuração de múltiplos LLM providers e CLI agents + roteamento.
- API, UI e CLI mínimas.

## 4. Não escopo (fora do MVP 1)

SaaS multiempresa; marketplace de agentes; billing; deploy automático em produção; execução remota distribuída; permissões avançadas por organização; integração obrigatória com todos os CLI agents; fork profundo do AgentWrapper; UI estilo Jira completo; execução autônoma destrutiva; alteração de secrets; provisionamento cloud automático; agentes modificando banco de produção.

## 5. Requisitos (macro)

**Funcionais:** orquestrações F1–F7 multimodo; `OrchestratorContext` versionado com snapshots O1–O7; Kanban operacional com automação por eventos; `MultiAgentDecisionEngine`; registry/supervisor/router/executor de agentes; `ContextPatch` + `ContextBus` (validação em 7 etapas); `ConflictDetector`; `ADRRegistry`; `QualityGateEngine`; `SnapshotEngine`; `HumanApprovalEngine`; `ToolRegistry` com permissões; `ExecutionProviders`; configuração de providers/CLI agents; observabilidade.

**Não funcionais:** rastreabilidade bidirecional; isolamento por projeto/agente (worktrees); segurança (secrets env-only, permissões por tool, aprovação humana para ações críticas); limites de custo/iterações/tempo; determinismo de fluxo; ID e timestamps em toda entidade.

**Restrições:** não copiar/acoplar ao AgentWrapper no MVP 1 (referência operacional); `ExecutionProvider` abstrato + mock antes de integração real; documentação, UI e comentários em pt-BR.

## 6. Critérios de aceite do MVP-1 (§35)

O MVP-1 será aceito quando o sistema conseguir: (1) criar uma orquestração; (2) gerar um `ExecutionPlan`; (3) criar um `OrchestratorContext`; (4) criar um Kanban board; (5) criar cards automaticamente; (6) decidir single-agent vs multi-agent; (7) executar ao menos um agente (simulado ou real); (8) produzir um `ContextPatch`; (9) validar e aplicar o patch pelo `ContextBus`; (10) registrar uma ADR; (11) rodar um quality gate simples; (12) gerar um snapshot; (13) exibir a timeline; (14) exibir o Kanban; (15) registrar logs básicos.

Detalhamento do escopo e backlog do MVP-1 em [`mvp/mvp-1.md`](mvp/mvp-1.md).

## Referências

- Requisitos completos: [`requerimentos.md`](../requerimentos.md)
- Discovery: [F1 — Discovery & Strategy](phases/F1-discovery.md)
- Arquitetura: [`architecture.md`](architecture.md)
- Contexto/governança: [`context.md`](context.md)
