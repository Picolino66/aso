# MEL-53 — Remover código morto e abstrações vazias

| Campo | Valor |
|---|---|
| Fase do roadmap | 5 — Limpeza |
| Prioridade | P2 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-17 (decisão sobre congelamento) |
| Origem | [feedback.md](../feedback.md) §7 |
| Requer ADR | Sim, curta: reduz o catálogo de papéis e estratégias (atualiza ADR-0001/ADR-0053 no que couber) |

## Itens

| Item | Evidência | Ação |
|---|---|---|
| `AgentExecutor` | [executor.py:65](../src/aso/agents/executor.py#L65), sem consumidores | Remover |
| `_agent_order` | Nenhuma chamada | Remover |
| `ContextBus._step_conflict_detection`, `_step_quality_gate_impact` | Sem efeito | Remover (ou implementar, se houver requisito real) |
| `ExecutionStrategy` com 9 valores | Só `plan.strategy` como rótulo; `AGENTS_AS_TOOLS`, `HANDOFF`, `GROUP_CHAT`, `HYBRID` nunca produzidos; `SUPERVISOR_WORKER` sem supervisor | Reduzir aos valores que mudam execução (após MEL-50) |
| `PlannedAgent.parallel_group`, `PlannedAgent.allowed_tools` | Persistidos, sem uso | Remover (com migration) |
| `AgentSpec.allowed_tools`, `requires_approval_for` | Nunca aplicados | Remover, ou aplicar com decisão explícita |
| `AgentDefinition`: `modelos_permitidos`, `efforts_permitidos`, `projetos`, `categorias_tarefa`, `exige_supervisao`, `plataforma` | Só persistidos | Aplicar (ex.: validar executor/effort permitido no `run_card`) ou marcar como informativo na UI |
| Papéis `OrchestratorAgent`, `ProductStrategyAgent`, `RequirementsAgent`, `UxPlanningAgent`, `ConflictResolutionAgent`, `FinalResponseAgent` | Nunca recebem card | Remover do registro ou marcar "reservado" |
| `ConflictType` `SECURITY`, `SCOPE`, `QUALITY_GATE`, `KANBAN_DEPENDENCY`, `PR`, `CI`, `REVIEW` | Nunca levantados | Remover |
| Card do `ReviewAgent` criado pelo motor de decisão | Duplica o `ReviewService`; executa pelo implementador genérico | Parar de criar o card; revisão acontece pela PR |
| Congelamento de snapshot | Depende da decisão de MEL-17 | Conforme ADR |
| `recover_invalid_execution`, `_LEGACY_CODEX_NAMES` | Reparo de dados antigos | Manter; registrar data de remoção |

## Critérios de aceite

- [ ] Cada item tratado conforme a coluna "Ação".
- [ ] Migrations para colunas removidas, validadas no Postgres.
- [ ] Documentação e UI sem referências aos itens removidos.
- [ ] Suíte verde; testes que só exercitavam código morto removidos junto.
