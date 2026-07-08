# SPEC — AgentRegistry

- **Card:** TASK-07
- **Épico:** EPIC-5 (Agentes)
- **Fase:** F5
- **ADRs:** —
- **Requisitos:** §15, §25, §40 Task 7
- **Depende de:** TASK-02

## Objetivo

Implementar o `AgentRegistry`: catálogo dos agentes internos obrigatórios (§15) com suas capacidades, tools permitidas (allowlist §25) e ações que exigem aprovação humana (`requires_approval_for`). É a base do `ToolPermissionEngine` e a fonte que o ExecutionPlanner e o AgentExecutor consultam para saber quem pode fazer o quê.

Entrega o registro dos 16 papéis do §15 e a checagem de permissão de tool por agente, sustentando o princípio de segurança "permissões de tools por agente" (F2 §7).

## Escopo

- Incluído:
  - Registro dos 16 agentes do §15: OrchestratorAgent, ProductStrategyAgent, RequirementsAgent, ArchitectureDesignAgent, DataApiContractsAgent, UxPlanningAgent, BackendDevelopmentAgent, FrontendDevelopmentAgent, DatabaseAgent, DevOpsAgent, TestingAgent, SecurityAgent, DocumentationAgent, ReviewAgent, ConflictResolutionAgent, FinalResponseAgent.
  - Cada `Agent`: `role`, `capabilities[]`, `allowed_tools[]`, `requires_approval_for[]`, `default_executor`.
  - `ToolPermissionEngine`: verifica se um agente pode usar uma tool e se a ação exige aprovação (§25.1).
  - Catálogo de tools iniciais (§25): read_file, write_file, search_repo, git_status, git_diff, create_branch, create_worktree, run_tests, run_lint, run_build, validate_openapi, validate_json_schema, create_adr, update_docs, open_pr, read_ci_status, read_review_comments, security_scan.
  - Seed/registro programático dos agentes na inicialização.
- Fora de escopo (MVP-1):
  - Detecção de instalação de CLI agents e teste de providers (§26A.3/§26A.4 — MVP posterior).
  - `AgentRoleBinding`/`ProviderConfig`/mapeamento a modelos reais (MVP posterior).
  - SkillRegistry/SkillResolver (MVP posterior).

## Comportamento esperado

- Os 16 papéis são registráveis e listáveis; cada um com allowlist de tools e lista `requires_approval_for`.
- `ToolPermissionEngine.can_use(agent_role, tool)` retorna verdadeiro apenas se a tool estiver na allowlist do agente.
- `ToolPermissionEngine.requires_approval(agent_role, action)` retorna verdadeiro para ações em `requires_approval_for` (ex.: BackendDevelopmentAgent ⇒ delete_file, database_reset, deploy — §25.1).
- Tool fora da allowlist é negada (não silenciosamente permitida) — insumo para TOOL_PERMISSION_CONFLICT (§20).
- Registro é idempotente: re-seed não duplica agentes (chave por `role`).
- `default_executor` no MVP-1 é `llm_provider` (execução real diferida; o executor concreto é o mock — ver [agent-executor-mock.md](agent-executor-mock.md)).

## Contratos / Interfaces

Módulo: `src/aso/agents/registry/`.

```python
# src/aso/agents/registry/agent_registry.py
class AgentRegistry:
    def register(self, agent: AgentDefinition) -> Agent: ...
    def get(self, role: str) -> Agent: ...
    def list(self) -> list[Agent]: ...
    def seed_default_agents(self) -> None: ...   # registra os 16 papéis do §15

# src/aso/agents/registry/tool_permission_engine.py
class ToolPermissionEngine:
    def can_use(self, agent_role: str, tool: str) -> bool: ...
    def requires_approval(self, agent_role: str, action: str) -> bool: ...

# schema (ver domain-models.md)
class Agent(BaseModel):
    id: UUID
    role: str
    capabilities: list[str]
    allowed_tools: list[str]
    requires_approval_for: list[str]
    default_executor: str            # llm_provider | cli_agent
    created_at: datetime
```

- Endpoints: `GET /v1/agents`, `GET /v1/agents/{id}` (ver [api-minimal.md](api-minimal.md)).

## Critérios de aceite

- [ ] Os 16 agentes do §15 são registráveis e listáveis.
- [ ] Permissões de tool por agente aplicadas (allowlist §25); tool fora da allowlist é negada.
- [ ] `requires_approval_for` respeitado por ação (§25.1).
- [ ] Seed é idempotente (não duplica por `role`).

## Rastreabilidade

§15/§25/§40 Task 7 → (sem ADR) → esta spec → TASK-07 → `src/aso/agents/registry/` (agent_registry, tool_permission_engine), tabela `agents` → `tests/unit/test_agent_registry.py`, `tests/unit/test_tool_permissions.py`
