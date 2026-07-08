# agents/ — Mapa de agentes (ownership)

> Estrutura agentic (F4). Detalhe de responsabilidades em [docs/agents.md](../docs/agents.md). Bindings de executor configuráveis em `.aso/providers.yaml` (§26A).

Os 16 agentes obrigatórios (§15) e sua área de ownership:

| Agente | Fase(s) | Owner de |
|---|---|---|
| OrchestratorAgent | F1–F7 | fluxo global, modo de execução, coordenação |
| ProductStrategyAgent | F1 | discovery, personas, escopo, métricas |
| RequirementsAgent | F1 | requisitos e rastreabilidade |
| ArchitectureDesignAgent | F2 | arquitetura, ADRs, stack, riscos |
| DataApiContractsAgent | F3 | contratos, schemas, OpenAPI |
| UxPlanningAgent | F4 | jornadas, backlog, Kanban |
| BackendDevelopmentAgent | F5 | backend, domínio, persistência |
| FrontendDevelopmentAgent | F5 | UI (diferida no MVP) |
| DatabaseAgent | F3/F5 | modelagem, migrations, performance |
| DevOpsAgent | F6 | CI/CD, deploy, observabilidade |
| TestingAgent | F5/F6 | testes e QA |
| SecurityAgent | F2/F5/F6 | segurança, threat model, secrets |
| DocumentationAgent | F5/F6 | documentação e ADRs |
| ReviewAgent | todas | revisão independente e aprovação |
| ConflictResolutionAgent | governança | conflitos e resolução |
| FinalResponseAgent | fechamento | consolidação de resultado |

Bindings padrão sugeridos (§26A.4): agentes de análise/planejamento → LLM provider (DeepSeek/OpenAI); agentes que alteram código → CLI agent (Claude Code/Codex) em worktree isolado; ReviewAgent → `best_available`.
