# Agentes — ASO Runtime

> Fase F4. Mapa dos 16 agentes obrigatórios (§15) com responsabilidade, plane e binding de executor sugerido (§26A). Índice operacional em [`agents/README.md`](../agents/README.md).

> **Papel × executor × função.** O *papel* (ex.: `BackendDevelopmentAgent`) é um rótulo com
> seções do contexto que pode escrever (`PermissionPolicy`) e fase padrão; o *executor* é o
> perfil do catálogo que roda a tarefa (mock, LLM via API ou CLI como Codex/Claude Code); a
> *função* de agente (naming, triagem, discovery, especificação, revisão) é uma pergunta em
> JSON feita a um executor (`perguntar_ao_agente`). Um mesmo executor pode servir a vários
> papéis e funções.
>
> **Papéis reservados** (`AgentSpec.reservado`, ADR-0075): `OrchestratorAgent`,
> `ProductStrategyAgent`, `RequirementsAgent`, `UxPlanningAgent` e `FinalResponseAgent` — nem o
> motor de decisão nem o planejamento LLM (`/plan`) mapeiam domínio para eles; seguem no
> catálogo e no registro de permissões, marcados como reservados no console
> (`GET /v1/agent-definitions/roles/reservados`). O motor não cria card de `ReviewAgent` (a
> revisão independente é a da PR, ADR-0017) e `ConflictResolutionAgent` recebe cards `ADRTask`
> de conflito.
>
> **Fase padrão do card de cada papel** (MEL-20): declarada em
> `FASE_PADRAO_POR_PAPEL` (`src/aso/agents/registry.py`) — F1: Orchestrator, ProductStrategy,
> Requirements · F2: ArchitectureDesign, Security · F3: DataApiContracts, Database ·
> F4: UxPlanning · F5: Backend, Frontend, ConflictResolution · F6: DevOps, Testing,
> Documentation, Review · F7: FinalResponse. Papel fora da tabela (catálogo customizado) cai
> em F5; o planejamento LLM e a spec podem fixar a fase explicitamente.

| Agente | Plane | Responsabilidade | Executor sugerido |
|---|---|---|---|
| OrchestratorAgent | control | Entender demanda, escolher modo, coordenar fases/agentes, preservar contexto, consolidar, pedir aprovação, bloquear avanço | llm_provider (reasoning) |
| ProductStrategyAgent | control (F1) | Discovery, visão, personas, hipóteses, escopo, métricas | llm_provider |
| RequirementsAgent | control (F1) | RF/RNF, critérios de aceite, rastreabilidade | llm_provider |
| ArchitectureDesignAgent | control (F2) | Arquitetura, padrões, stack, módulos, integrações, ADRs, riscos | llm_provider (reasoning) |
| DataApiContractsAgent | governance (F3) | Contratos, OpenAPI, schemas, entidades, DTOs, versionamento, consistência | llm_provider (reasoning) |
| UxPlanningAgent | control (F4) | Jornadas, fluxos, telas, backlog, tasks, Kanban | llm_provider |
| BackendDevelopmentAgent | execution (F5) | Backend, endpoints, services, domínio, persistência, testes backend | cli_agent (claude_code, fallback codex) |
| FrontendDevelopmentAgent | execution (F5) | UI, componentes, páginas, integração API, estados, testes frontend | cli_agent |
| DatabaseAgent | execution | Modelagem, migrations, índices, queries, performance | cli_agent / llm_provider |
| DevOpsAgent | execution (F6) | CI/CD, Docker, deploy, ambientes, observabilidade, rollback | cli_agent |
| TestingAgent | execution (F5/F6) | Testes unit/integração/contrato/e2e, plano de QA | cli_agent (codex, fallback claude_code) |
| SecurityAgent | governance | Threat model, authn/authz, validação, secrets, deps, vulnerabilidades | llm_provider / cli_agent |
| DocumentationAgent | execution | README, docs, ADRs, guias, changelog, docs de API | llm_provider |
| ReviewAgent | governance | Revisão independente, aderência a arquitetura/contratos, riscos, aprovação | strategy: best_available |
| ConflictResolutionAgent | governance | Analisar conflitos, propor resolução, sugerir ADR, pedir aprovação | llm_provider (reasoning) |
| FinalResponseAgent | control | Consolidar execução, resumir decisões/entregas/pendências/riscos/próximos passos | llm_provider |

## Saída obrigatória do ReviewAgent (§15.14)

```json
{ "status": "approved | changes_requested | rejected", "findings": [], "risks": [], "required_changes": [], "quality_gate_impact": [], "recommendation": "..." }
```

## Permissões de tools (§25)

Não há permissão de ferramenta por papel: `allowed_tools`/`requires_approval_for` nunca foram
aplicados e saíram na MEL-53 (ADR-0075); `ferramentas` do catálogo de agentes é informativo. O
que é imposto hoje é a permissão de escrita no
contexto (`PermissionPolicy` do ContextBus) e o isolamento em worktree para agentes que alteram
código (§26A.6).
