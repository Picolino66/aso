# SPEC — MultiAgentDecisionEngine básico

- **Card:** TASK-06
- **Épico:** EPIC-4 (Planejamento & Decisão)
- **Fase:** F5
- **ADRs:** —
- **Requisitos:** §13, §14, §40 Task 6
- **Depende de:** TASK-03

## Objetivo

Implementar o componente que decide a estratégia de execução de uma demanda (§14): quando usar um único agente (single_agent) e quando usar múltiplos agentes, com justificativa (`reason`), nível de risco e sinalização de necessidade de aprovação humana. Prepara a arquitetura para os padrões multiagente do §13, ainda que o MVP-1 execute principalmente single_agent com agente mock.

A decisão alimenta o [execution-plan.md](execution-plan.md). O engine não deve criar múltiplos agentes sem necessidade (§8.2).

## Escopo

- Incluído:
  - Entrada do §14 (`user_request`, `current_phase`, `orchestrator_context`, `available_agents/skills/tools`, `risk_level`, `constraints`, `budget`, `deadline`).
  - Saída do §14 (`execution_mode`, `reason`, `risk_level`, `requires_human_approval`, `agents[]`, `success_criteria`, `fallback_strategy`).
  - Regras de decisão single vs multi-agent (§14): usa múltiplos agentes quando há múltiplos domínios, risco relevante, necessidade de revisão independente, tarefas paralelizáveis ou impacto em arquitetura/contrato/segurança/banco/deploy; evita múltiplos agentes para tarefas pequenas/textuais simples.
  - Marcação `requires_human_approval=true` quando `risk_level` for high/critical.
- Fora de escopo (MVP-1):
  - Implementação executável dos padrões avançados (group_chat_controlled, evaluator_optimizer, supervisor_worker) — apenas classificáveis como `execution_mode`, sem runtime dedicado (MVP-2).
  - Roteamento de executor por provider/CLI (AgentRouter §26A — MVP posterior).
  - Aprendizado por histórico de sucesso (§26A.7) — heurística estática no MVP-1.

## Comportamento esperado

- Dada a entrada, o engine retorna uma decisão com `execution_mode` ∈ {single_agent, sequential_agents, parallel_agents, agents_as_tools, handoff, supervisor_worker, group_chat_controlled, evaluator_optimizer, hybrid} e `reason` textual não-vazio.
- Regra base: por padrão, tarefa de baixo risco e domínio único → `single_agent`. Múltiplos domínios/risco/paralelismo/revisão independente → estratégia multi-agent apropriada.
- `risk_level` de saída ≥ risco de entrada quando a análise elevar o risco; se high/critical → `requires_human_approval=true`.
- `agents[]` lista `PlannedAgent` coerentes com o modo (ex.: single_agent ⇒ 1 agente primário).
- `success_criteria` e `fallback_strategy` sempre presentes.
- Determinístico para a mesma entrada (heurística baseada em regras, sem chamada LLM obrigatória no MVP-1).

## Contratos / Interfaces

Módulo: `src/aso/control/decision/`.

```python
# src/aso/control/decision/multiagent_decision_engine.py
class DecisionInput(BaseModel):
    user_request: str
    current_phase: PhaseCode
    orchestrator_context: dict
    available_agents: list[str] = []
    available_skills: list[str] = []
    available_tools: list[str] = []
    risk_level: RiskLevel = RiskLevel.low
    constraints: dict = {}
    budget: dict = {}
    deadline: datetime | None = None

class DecisionOutput(BaseModel):
    execution_mode: Strategy
    reason: str
    risk_level: RiskLevel
    requires_human_approval: bool
    agents: list[PlannedAgent]
    success_criteria: list[str]
    fallback_strategy: str

class MultiAgentDecisionEngine:
    def decide(self, data: DecisionInput) -> DecisionOutput: ...
```

## Critérios de aceite

- [ ] Decide `execution_mode` com `reason` não-vazio.
- [ ] Marca `requires_human_approval=true` quando o risco é high/critical.
- [ ] Aplica as regras single vs multi-agent do §14 (múltiplos domínios/risco/paralelismo ⇒ multi-agent; tarefa simples ⇒ single_agent).
- [ ] Saída inclui `agents`, `success_criteria` e `fallback_strategy`.

## Rastreabilidade

§13/§14/§40 Task 6 → (sem ADR) → esta spec → TASK-06 → `src/aso/control/decision/multiagent_decision_engine.py` → `tests/unit/test_multiagent_decision_engine.py`
