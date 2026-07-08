# F1 — Discovery & Strategy — ASO Runtime

> Documento canônico da fase F1. Consolida e valida o discovery a partir de [requerimentos.md](../../requerimentos.md).
> Estado: **F1 concluída — snapshot O1 gerado**.

## 1. Visão do produto

**ASO Runtime — Autonomous Software Orchestrator Runtime** é um runtime multiagente de engenharia de software com Kanban operacional, capaz de decompor demandas, distribuir tarefas entre agentes especializados, executar em paralelo, validar por quality gates, registrar ADRs, gerar snapshots e conduzir o ciclo completo da ideia à produção.

Atua como combinação de: CTO agentic, Tech Lead agentic, Product/Engineering Manager agentic, orquestrador multiagente, Kanban operacional, runtime de execução de agentes, governança de arquitetura e rastreador de decisões/tarefas/contexto/qualidade/evolução.

## 2. Objetivo

Transformar uma intenção (produto, feature, melhoria técnica, refatoração, incidente ou evolução) em um fluxo rastreável de ponta a ponta, coordenando múltiplos agentes especializados com contexto canônico soberano e governança por fases.

## 3. Público-alvo e personas

| Persona | Papel | Principal dor | Principal objetivo |
|---|---|---|---|
| Tech Lead / Dev sênior orquestrador | Conduz o desenvolvimento com múltiplos agentes | Agentes perdem contexto global e contrariam decisões | Distribuir trabalho rastreável e executar em paralelo com segurança |
| Engenheiro de Plataforma / Arquiteto | Governança técnica | Agentes alteram arquitetura/contratos/escopo sem validação | Impor gates, ADRs e aprovação humana |
| Product/Engineering Manager agentic | Acompanhamento de entrega | Falta de visibilidade do estado real e do custo | Ver progresso por fase/card, custo e bloqueios |

## 4. Problemas que o produto resolve

Ferramentas atuais de agentes de código implementam tarefas mas falham em: manter contexto global; preservar decisões arquiteturais; evitar conflitos entre agentes; organizar trabalho em Kanban; conectar discovery→arquitetura→contrato→UX→código→testes→deploy→operação; garantir quality gates; rastrear requisito→decisão→task→implementação→teste→deploy; impedir alterações não validadas de contrato/arquitetura/escopo; coordenar tarefas paralelas com segurança; decidir quando usar 1 ou N agentes, paralelismo, handoff ou aprovação humana.

## 5. Hipóteses

- Governança soberana (ContextBus + snapshots + gates) permite coordenar N agentes sem degradar consistência.
- Kanban como plano de execução (não apenas visual) basta para controlar a operação dos agentes.
- Um `MultiAgentDecisionEngine` escolhe a estratégia de execução adequada por demanda.
- É viável abstrair execução em `ExecutionProvider` e começar por mock antes de integrar CLI agents reais.

## 6. Escopo (incluído no MVP)

- Multiagentes em multitarefas com isolamento e controle central.
- Quadro Kanban como mecanismo de controle operacional.
- Orquestração ponta a ponta F1–F7.
- Governança: contexto canônico, ADRs, quality gates, snapshots, aprovações.
- Configuração de múltiplos LLM providers e CLI agents + roteamento.
- API, UI e CLI mínimas.

## 7. Não escopo (fora do MVP 1)

SaaS multiempresa; marketplace de agentes; billing; deploy automático em produção; execução remota distribuída; permissões avançadas por organização; integração obrigatória com todos os CLI agents; fork profundo do AgentWrapper; UI estilo Jira completo; execução autônoma destrutiva; alteração de secrets; provisionamento cloud automático; agentes modificando banco de produção.

## 8. Requisitos iniciais

**Funcionais (macro):** orquestrações F1–F7 multimodo; OrchestratorContext versionado com snapshots O1–O7; Kanban operacional; MultiAgentDecisionEngine; registry/supervisor/router/executor de agentes; ContextPatch + ContextBus (validação em 7 etapas); ConflictDetector; ADRRegistry; QualityGateEngine; SnapshotEngine; HumanApprovalEngine; ToolRegistry com permissões; ExecutionProviders; configuração de providers/CLI agents; API/UI/CLI mínimas; observabilidade.

**Não funcionais:** rastreabilidade bidirecional; isolamento por projeto/agente (worktrees); segurança (secrets, permissões, aprovação humana); limites de custo/iterações/tempo; determinismo de fluxo; IDs e timestamps em toda entidade.

## 9. Métricas de sucesso (critérios de aceite do MVP 1)

Orquestração criável; ExecutionPlan gerado; OrchestratorContext criado e versionado; Kanban board + cards automáticos; decisão single vs multi-agent com justificativa; ao menos um agente (mock) executa; ContextPatch validado e aplicado pelo ContextBus; ao menos uma ADR registrada; quality gate simples executado; snapshot gerado; timeline e logs básicos exibidos.

## 10. Riscos iniciais

| ID | Risco | Mitigação |
|---|---|---|
| RISK-01 | Coordenar múltiplos agentes paralelos mantendo consistência | ContextBus soberano + ConflictDetector + snapshots imutáveis; começar com mock |
| RISK-02 | Integração heterogênea com CLI agents e adapters | AgentAdapter contract abstrato; adiar para MVP 3/4 |
| RISK-03 | Custo/tokens em execuções longas | CostTracker, budgets, CompressionEngine |
| RISK-04 | Escopo amplo → over-engineering | Roadmap incremental MVP 1→5; core primeiro |
| RISK-05 | Ações destrutivas de agentes | HumanApprovalEngine + worktree isolado + tools com permissão |

## 11. Viabilidade

**Veredito: VIÁVEL COM RISCOS.** A arquitetura conceitual é sólida e o roadmap incremental (MVP 1 sem execução real de código) reduz risco de over-engineering. Riscos concentrados em concorrência de agentes, integração com CLI agents e custo — todos com mitigação definida.

## 12. Quality Gate F1 → F2

| Critério | Status | Evidência |
|---|---|---|
| ≥ 2 personas estruturadas com dores e objetivos | ✅ PASSED | 3 personas (seção 3) |
| MVP hypothesis declarada e validada | ✅ PASSED | Seções 5 e 9 |
| Escopo com limites explícitos (incluído/excluído) | ✅ PASSED | Seções 6 e 7 |
| Métricas de sucesso mensuráveis | ✅ PASSED | Seção 9 (15 critérios de aceite) |
| Viabilidade avaliada como VIÁVEL/VIÁVEL_COM_RISCOS | ✅ PASSED | Seção 11 |

**Resultado: PASSED → snapshot O1 gerado. Apto a avançar para F2 (Architecture & Design) mediante aprovação.**
