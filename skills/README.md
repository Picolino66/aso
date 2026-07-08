# skills/ — Mapa de skills reutilizáveis

> Estrutura agentic (F4). Skills são capacidades/checklists/procedimentos reutilizáveis (§ glossário) que agentes invocam.

Skills previstas para o MVP (evoluem por fase):

| Skill | Usada por | Propósito |
|---|---|---|
| `requirements-elicitation` | ProductStrategyAgent, RequirementsAgent | Extrair e estruturar requisitos e critérios de aceite |
| `adr-authoring` | ArchitectureDesignAgent, ReviewAgent | Redigir ADRs no formato §21 |
| `openapi-authoring` | DataApiContractsAgent | Gerar/validar OpenAPI e DTOs |
| `backlog-decomposition` | UxPlanningAgent | Decompor épicos em tasks com critérios de aceite |
| `context-patch-authoring` | todos os agentes | Produzir ContextPatch válido para o ContextBus |
| `code-review-checklist` | ReviewAgent | Revisão de arquitetura, contratos, segurança, riscos |
| `test-planning` | TestingAgent | Planejar testes unit/integração/contrato/e2e |
| `conflict-resolution` | ConflictResolutionAgent | Analisar conflitos e propor resolução/ADR |

O `SkillResolver` (Agent Plane) seleciona a skill mais adequada; o `ExternalSkillResolver` pode delegar para skills externas mais especializadas (transversal F2–F7).
