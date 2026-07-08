# SPEC — ExecutionPlan a partir de solicitação

- **Card:** TASK-05
- **Épico:** EPIC-4 (Planejamento & Decisão)
- **Fase:** F5
- **ADRs:** —
- **Requisitos:** §14, §40 Task 5
- **Depende de:** TASK-03

## Objetivo

Gerar, a partir de uma solicitação do usuário (`user_request`) e do contexto corrente, um `ExecutionPlan` que descreve como a demanda será executada: estratégia multiagente, agentes planejados com papéis e tools, critérios de sucesso e estratégia de fallback (§14).

O plano é o artefato que conecta a intenção do usuário à orquestração concreta (cards, agentes). Consome a decisão do [multiagent-decision-engine.md](multiagent-decision-engine.md) para preencher `strategy`/`agents` e persiste o resultado como entidade `ExecutionPlan` associada à orquestração.

## Escopo

- Incluído:
  - Geração de `ExecutionPlan` a partir de `user_request` + `OrchestratorContext` + `execution_mode`.
  - Preenchimento de `strategy`, `reason`, `risk_level`, `requires_human_approval`, `agents (list<PlannedAgent>)`, `success_criteria`, `fallback_strategy`.
  - `PlannedAgent`: `{ agent, role, reason, allowed_tools, depends_on, parallel_group }`.
  - Persistência e leitura do plano (`GET /v1/orchestrations/{id}/plan`).
- Fora de escopo (MVP-1):
  - Otimização de custo/deadline/budget do §14 (campos aceitos, mas sem otimização real).
  - Re-planejamento dinâmico durante a execução (MVP-2).
  - Grafo de dependências executável (DependencyGraph completo — MVP-2); aqui `depends_on` é declarativo.

## Comportamento esperado

- Dado `user_request`, `current_phase` e o contexto, o serviço produz um `ExecutionPlan` válido com pelo menos um `PlannedAgent`.
- A `strategy` e a lista de `agents` derivam da decisão do MultiAgentDecisionEngine (§14); `reason` explica a escolha.
- `success_criteria` é não-vazio e descreve condições verificáveis de conclusão (insumo para o QualityGateEngine).
- `fallback_strategy` descreve o que fazer se a execução falhar (ex.: fallback de agente, escalonamento humano).
- Quando o risco for alto/crítico, `requires_human_approval=true` (coerente com a decisão do engine e §8.6).
- O plano é persistido e recuperável; um plano por orquestração no MVP-1 (regeneração substitui).

## Contratos / Interfaces

Módulo: `src/aso/control/planning/`.

```python
# src/aso/control/planning/execution_planner.py
class ExecutionPlanner:
    def __init__(self, decision_engine: MultiAgentDecisionEngine): ...
    async def build_plan(
        self,
        orchestration_id: UUID,
        user_request: str,
        execution_mode: str,
        context: OrchestratorContext,
    ) -> ExecutionPlan: ...

# schema (ver domain-models.md)
class PlannedAgent(BaseModel):
    agent: str
    role: str                    # primary | support | reviewer | ...
    reason: str
    allowed_tools: list[str] = []
    depends_on: list[str] = []
    parallel_group: str | None = None

class ExecutionPlan(BaseModel):
    id: UUID
    orchestration_id: UUID
    execution_mode: str
    strategy: Strategy           # single_agent | sequential_agents | ...
    reason: str
    risk_level: RiskLevel
    requires_human_approval: bool
    agents: list[PlannedAgent]
    success_criteria: list[str]
    fallback_strategy: str
    created_at: datetime
```

- Endpoint: `GET /v1/orchestrations/{id}/plan` (ver [api-minimal.md](api-minimal.md)).

## Critérios de aceite

- [ ] Plano é gerado a partir de `user_request` (+ contexto/modo).
- [ ] Plano contém agentes (`PlannedAgent`) e `success_criteria` não-vazios.
- [ ] `strategy` e `risk_level` refletem a decisão do MultiAgentDecisionEngine; `fallback_strategy` presente.
- [ ] `requires_human_approval` coerente com o risco.

## Rastreabilidade

§14/§40 Task 5 → (sem ADR) → esta spec → TASK-05 → `src/aso/control/planning/execution_planner.py`, tabela `execution_plans` → `tests/unit/test_execution_planner.py`
