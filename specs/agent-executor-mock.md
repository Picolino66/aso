# SPEC — AgentExecutor mock

- **Card:** TASK-08
- **Épico:** EPIC-5 (Agentes)
- **Fase:** F5
- **ADRs:** ADR-0001
- **Requisitos:** §26, §43, §40 Task 8
- **Depende de:** TASK-07

## Objetivo

Definir a abstração `ExecutionProvider` e entregar o `LocalMockExecutionProvider`, que simula a execução de um agente e retorna um output estruturado — incluindo `ContextPatch` — sem executar código real (§43: implementar provider abstrato; provider local/mock primeiro; MVP-1 não executa código real, §36).

Isto valida o núcleo de governança (Kanban → agente → patch → ContextBus → gate → snapshot) ponta a ponta sem depender de CLI agents ou LLMs reais. Segue a regra de dependência de ADR-0001 (execução é adapter; domínio não depende dela).

## Escopo

- Incluído:
  - Interface abstrata `ExecutionProvider` (contrato mínimo inspirado no §27, reduzido ao necessário para o MVP-1).
  - `LocalMockExecutionProvider` que produz `AgentRun` + `AgentOutput` determinístico e um ou mais `ContextPatch` estruturados (§18).
  - `AgentExecutor` que resolve o provider, cria `AgentRun`, executa e coleta o resultado, respeitando permissões do [agent-registry.md](agent-registry.md).
  - Registro de `AgentRun` com status (running→completed/failed) e timestamps.
- Fora de escopo (MVP-1):
  - Execução real de código, worktrees, terminal, git (`LocalCliExecutionProvider`/`AgentWrapperExecutionProvider` — §43 passos 6–7, MVP-3+).
  - Chamadas a LLM providers reais / streaming.
  - Nudge/resume/coleta de artefatos reais (métodos podem existir como no-op).

## Comportamento esperado

- `AgentExecutor.run(card, agent_role)` cria um `AgentRun` (`status=running`), invoca o provider e, ao concluir, marca `status=completed` com `finished_at`.
- O `LocalMockExecutionProvider` retorna um output estruturado contendo ao menos um `ContextPatch` válido (com `target_path`, `content`, `patch_type`, `agent`, `phase`) pronto para submissão ao ContextBus.
- Antes de executar uma tool, o executor consulta o `ToolPermissionEngine`; tool não permitida faz o run falhar com erro claro (não executa).
- Execução do mock é determinística/configurável (permite testes reproduzíveis e cenários de falha).
- O `AgentRun` é rastreável (orchestration_id, card_id, agent_role, executor_type=`llm_provider`/mock, status, timestamps) — insumo de observabilidade (§33).
- O patch produzido NÃO é aplicado diretamente ao contexto; é entregue ao ContextBus (§8.3 / ADR-0003).

## Contratos / Interfaces

Módulos: `src/aso/execution/providers/`, `src/aso/agents/executor/`.

```python
# src/aso/execution/providers/base.py
class ExecutionProvider(ABC):
    @abstractmethod
    async def execute(self, request: ExecutionRequest) -> ExecutionResult: ...

# src/aso/execution/providers/local_mock.py
class LocalMockExecutionProvider(ExecutionProvider):
    async def execute(self, request: ExecutionRequest) -> ExecutionResult: ...
    # retorna ExecutionResult com context_patches: list[ContextPatch]

# src/aso/agents/executor/agent_executor.py
class AgentExecutor:
    def __init__(self, registry: AgentRegistry, permissions: ToolPermissionEngine, provider: ExecutionProvider): ...
    async def run(self, orchestration_id: UUID, card_id: UUID, agent_role: str) -> AgentRun: ...

class ExecutionResult(BaseModel):
    agent_run_id: UUID
    status: AgentRunStatus         # completed | failed | cancelled
    output: dict
    context_patches: list[ContextPatch]
    logs_ref: str | None = None
```

- Endpoints: `POST /v1/cards/{id}/run`, `POST /v1/agents/{id}/run`, `GET /v1/agents/{id}/runs` (ver [api-minimal.md](api-minimal.md)).

## Critérios de aceite

- [ ] `ExecutionProvider` abstrato definido; `LocalMockExecutionProvider` implementa e executa.
- [ ] O provider mock retorna `ContextPatch` estruturado (válido para o ContextBus).
- [ ] `AgentRun` é criado e transiciona running→completed/failed com timestamps.
- [ ] Tool não permitida (ToolPermissionEngine) faz o run falhar sem executar.

## Rastreabilidade

§26/§43/§40 Task 8 → ADR-0001 → esta spec → TASK-08 → `src/aso/execution/providers/base.py`, `src/aso/execution/providers/local_mock.py`, `src/aso/agents/executor/agent_executor.py`, tabela `agent_runs` → `tests/unit/test_local_mock_provider.py`, `tests/integration/test_agent_executor.py`
