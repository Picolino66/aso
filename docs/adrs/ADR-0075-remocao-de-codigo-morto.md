# ADR-0075 — Remoção de código morto e de abstrações que não mudavam a execução

- **Status:** ACCEPTED
- **Fase:** F5 (limpeza — MEL-53, origem `feedback.md` §7)
- **Data:** 2026-09-15
- **Atualiza:** [ADR-0001](ADR-0001-runtime-architecture.md) (catálogo de estratégias e papéis) e
  [ADR-0053](ADR-0053-catalogo-de-agentes.md) (campos do catálogo de agentes)
- **Relaciona-se com:** [ADR-0074](ADR-0074-paralelismo-por-onda.md) (estratégia define o
  paralelismo), [ADR-0017](ADR-0017-revisao-independente-de-codigo.md) (revisão pela PR),
  [ADR-0061](ADR-0061-congelamento-de-snapshot.md) (congelamento mantido)

## Contexto

A auditoria listou código que existia sem efeito: um executor sem consumidores, uma ordenação
nunca chamada, duas etapas vazias no ContextBus, sete estratégias que eram só rótulos, campos
persistidos e nunca lidos, papéis sem card, tipos de conflito nunca levantados e um card de
`ReviewAgent` que duplicava o `ReviewService`. Cada um parecia uma capacidade que o runtime não tem.

## Decisão (item a item, conferido contra o código em 2026-09-15)

| Item | Decisão |
|---|---|
| `AgentExecutor` | Removido (o teste passa a usar o provider simulado direto). |
| `_agent_order` | Removido (a ordem é das ondas, ADR-0074). |
| `ContextBus._step_conflict_detection` / `_step_quality_gate_impact` | Removidos: o pipeline tem **6 etapas**; não havia requisito para implementá-los. |
| `ExecutionStrategy` | Só `single_agent`, `sequential_agents`, `parallel_agents` — as que mudam a execução (ADR-0074). `evaluator_optimizer` e `supervisor_worker` viram `sequential_agents` com o motivo preservado; migration `c3986f6a1a5d` converte planos gravados. |
| `PlannedAgent.parallel_group` / `allowed_tools` | Removidos (colunas de `planned_agents` apagadas na mesma migration). |
| `AgentSpec.allowed_tools` / `requires_approval_for` | Removidos: nunca aplicados. A permissão real continua `context_sections`. |
| `AgentDefinition`: `plataforma`, `modelos_permitidos`, `efforts_permitidos`, `ferramentas`, `projetos`, `categorias_tarefa`, `exige_supervisao` | **Informativos**: persistidos e exibidos, marcados assim no console e no modelo. Aplicá-los (ex.: recusar executor fora de `modelos_permitidos`) mudaria a execução de todo agente-exemplo semeado — fica para uma decisão futura com o operador. |
| Papéis sem card (`OrchestratorAgent`, `ProductStrategyAgent`, `RequirementsAgent`, `UxPlanningAgent`, `FinalResponseAgent`) | **Reservados** (`AgentSpec.reservado`, `GET /v1/agent-definitions/roles/reservados`): seguem no registro e no catálogo. `ConflictResolutionAgent` **recebe** cards `ADRTask` — fica ativo (a evidência da auditoria estava desatualizada). |
| `ConflictType` `SECURITY`, `SCOPE`, `QUALITY_GATE`, `KANBAN_DEPENDENCY`, `PR`, `CI`, `REVIEW` | Removidos (nunca levantados). |
| Card do `ReviewAgent` criado pelo motor de decisão | Não é mais criado: a revisão independente acontece na PR (`ReviewService`, ADR-0017). |
| Congelamento de snapshot | Mantido (ADR-0061). |
| `recover_invalid_execution`, `_LEGACY_CODEX_NAMES` | Mantidos para reparo de dados antigos; revisar remoção a partir de **2027-03-15**. |

## Consequências

- Equipes multiagente do motor de decisão têm só os workers de domínio; F6 fica sem card
  automático (gate `SKIPPED` quando não há outro trabalho), e dependências entre cards vêm do
  plano LLM, da especificação ou do operador.
- Testes que usavam o card do `ReviewAgent` como exemplo de dependência passaram a criar a
  dependência explicitamente (plano com `TestingAgent` dependente, ou card adicionado).
- Documentos de fase e de MVP antigos (`docs/phases`, `docs/mvp`) continuam citando os nomes
  removidos como histórico de planejamento.
