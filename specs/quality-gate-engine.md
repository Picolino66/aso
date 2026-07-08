# SPEC — QualityGateEngine básico

- **Card:** TASK-11
- **Épico:** EPIC-6 (Governança)
- **Fase:** F5
- **ADRs:** —
- **Requisitos:** §22, §40 Task 11
- **Depende de:** TASK-03

## Objetivo

Implementar o `QualityGateEngine` que valida critérios objetivos de uma fase e produz um `QualityGateResult` (§22) com status `PASSED | FAILED | WARNING`. Quality gates bloqueiam o avanço de fase (§8.5): se o gate falha, a orquestração não progride. Gates falhos podem gerar cards automáticos para corrigir os problemas.

O gate aprovado é o pré-requisito para gerar snapshot (§22, ver [snapshot-engine.md](snapshot-engine.md)) e para o avanço de fase controlado pelo PhaseController.

## Escopo

- Incluído:
  - Modelo `QualityGateResult` (§22): `phase`, `status`, `criteria[{name,status,evidence,failure_reason}]`, `blocking_issues[]`, `warnings[]`, `required_actions[]`, `human_approval_required`, `human_approval_status`.
  - Execução de critérios simples por fase (regras declarativas/checagens booleanas sobre o contexto e cards).
  - Bloqueio de avanço quando `status=FAILED`.
  - Geração de cards automáticos a partir de `required_actions`/`blocking_issues` (tipo Task/Bug no board).
  - `WARNING` não bloqueia mas registra avisos.
- Fora de escopo (MVP-1):
  - Execução real de build/lint/test/CI como evidência (§22 evidências reais — MVP-3+); no MVP-1 os critérios são checagens de completude/consistência do contexto.
  - Gate crítico com fluxo completo de aprovação humana automatizado (campo existe; enforcement completo — MVP-2).
  - Acionamento automático do agente responsável (§22 — MVP-2); MVP-1 apenas gera cards.

## Comportamento esperado

- `run(orchestration_id, phase)` avalia os critérios definidos para a fase e retorna um `QualityGateResult` com `status` agregado.
- Regra de agregação: qualquer critério `FAILED` → `status=FAILED`; nenhum FAILED mas há avisos → `WARNING`; todos OK → `PASSED`.
- `FAILED` bloqueia o avanço de fase (o PhaseController/serviço de avanço recusa progredir).
- Em `FAILED`, o engine pode gerar cards automáticos (§22) a partir de `required_actions`/`blocking_issues`, ligados à orquestração e à fase.
- Cada critério registra `evidence` (referências) e, se falho, `failure_reason`.
- Gate `PASSED` habilita a geração de snapshot da fase (§23).
- Se `human_approval_required=true` (gate crítico), o resultado fica pendente de aprovação antes de contar como aprovado.

## Contratos / Interfaces

Módulo: `src/aso/governance/gates/`.

```python
# src/aso/governance/gates/quality_gate_engine.py
class QualityGateEngine:
    def __init__(self, ctx: OrchestratorContextService, cards: CardService): ...
    async def run(self, orchestration_id: UUID, phase: PhaseCode) -> QualityGateResult: ...
    def register_criteria(self, phase: PhaseCode, criteria: list[Criterion]) -> None: ...

class Criterion(BaseModel):
    name: str
    check: Callable[[GateContext], CriterionOutcome]   # regra simples

class QualityGateResult(BaseModel):
    id: UUID
    orchestration_id: UUID
    phase: PhaseCode
    status: GateStatus                # PASSED | FAILED | WARNING
    criteria: list[CriterionResult]
    blocking_issues: list[str] = []
    warnings: list[str] = []
    required_actions: list[str] = []
    human_approval_required: bool = False
    human_approval_status: str | None = None
    created_at: datetime
```

- Endpoints: `GET /v1/orchestrations/{id}/quality-gates`, `POST /v1/orchestrations/{id}/quality-gates/run`, `GET /v1/quality-gates/{id}` (ver [api-minimal.md](api-minimal.md)).

## Critérios de aceite

- [ ] Gate roda e retorna `PASSED`/`FAILED`/`WARNING` com `criteria` detalhados.
- [ ] `FAILED` bloqueia o avanço de fase.
- [ ] Gate falho pode gerar cards automáticos (Task/Bug) a partir de `required_actions`/`blocking_issues`.
- [ ] Gate `PASSED` habilita a geração de snapshot.

## Rastreabilidade

§22/§40 Task 11 → (sem ADR) → esta spec → TASK-11 → `src/aso/governance/gates/quality_gate_engine.py`, tabela `quality_gate_results` → `tests/unit/test_quality_gate_engine.py`
