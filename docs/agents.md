# Agentes — ASO Runtime

> Fase F4. Mapa dos 16 agentes obrigatórios (§15) com responsabilidade, plane e binding de executor sugerido (§26A). Índice operacional em [`agents/README.md`](../agents/README.md).

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

Cada agente tem `allowed_tools` e `requires_approval_for` no `ToolPermissionEngine`. Agentes que alteram código rodam em worktree isolado (§26A.6).
