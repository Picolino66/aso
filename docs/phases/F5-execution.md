# F5 — Engineering Execution — ASO Runtime

> Fase F5 **concluída**. Depende de O4. **MVP-1 completo: 15/15 cards, 15/15 critérios de aceite (§35).** Gate F5→F6 **PASSED** (48 testes, cobertura 98%, ruff+mypy OK) — snapshot **O5** gerado, aguardando aprovação humana para F6.

## Estado final do MVP-1

- **Cards:** TASK-01..15 → `Done`.
- **Código:** `src/aso/{shared,governance,agents,kanban,control,execution(mock),observability(events),api,cli}`.
- **Qualidade:** 48 testes (unit + integração), cobertura **98%** (threshold 80%), `ruff` limpo, `mypy --strict` limpo.
- **Superfície:** API FastAPI v1 (`aso.api.app:app`) + CLI Typer (`python -m aso.cli.main`).

### Critérios de aceite §35 — 15/15 ✅
criar orquestração · ExecutionPlan · OrchestratorContext · Kanban board · cards automáticos · decisão single/multi · executar agente (mock) · ContextPatch · ContextBus valida/aplica · ADR · quality gate · snapshot · timeline · Kanban exibido · logs básicos.

---

## Histórico — marco 1 (core de governança)

## Marco entregue — Core de governança

Implementação real em Python (ADR-0004) do coração do runtime. Cards concluídos: **TASK-01, 02, 03, 09, 10, 11, 12**.

| Card | Entregue | Módulo |
|---|---|---|
| TASK-01 | Estrutura base + tooling (pyproject, ruff, mypy, pytest, docker-compose) | raiz + `src/aso/` |
| TASK-02 | Modelos de domínio (Pydantic v2): ContextPatch, Conflict, QualityGateResult, Snapshot, ADR | `src/aso/governance/models.py` |
| TASK-03 | OrchestratorContext versionado (JSONB-ready, histórico append-only, hash) | `src/aso/governance/context_store.py` |
| TASK-09 | ContextPatch + ContextBus (pipeline de 7 etapas §19) | `src/aso/governance/contextbus.py` |
| TASK-10 | ADRRegistry (numeração sequencial, supersede) | `src/aso/governance/adr_registry.py` |
| TASK-11 | QualityGateEngine (critérios por fase, bloqueio) | `src/aso/governance/quality_gate_engine.py` |
| TASK-12 | SnapshotEngine (congela seções, restore) | `src/aso/governance/snapshot_engine.py` |
| — | ConflictDetector + EventLog + ids/types compartilhados | `governance/conflict_detector.py`, `shared/` |

## Estrutura de código

```
src/aso/
  __init__.py
  shared/        ids.py · types.py · events.py
  governance/    models.py · context_store.py · contextbus.py · conflict_detector.py
                 adr_registry.py · quality_gate_engine.py · snapshot_engine.py
tests/
  unit/          test_context_store · test_contextbus · test_quality_gate_engine
                 test_snapshot_engine · test_adr_registry
  integration/   test_governance_flow
```

## Evidências (Definition of Done §42)

- **Testes:** 24 passando (23 unit + 1 integração).
- **Lint:** `ruff check src tests` → All checks passed.
- **Type-check:** `mypy src` (strict) → Success, no issues.
- **ContextBus:** as 7 etapas de validação (§19) exercitadas — permissão, snapshot lock (com/sem ADR override), consistência de ADR, compatibilidade de contrato, schema.
- **Fluxo integração:** ADR → patch aplicado → gate PASSED → snapshot O2 → escrita em seção congelada bloqueada → eventos registrados.

## Critérios de aceite do MVP-1 cobertos por este marco

Dos 15 critérios (§35), este marco já satisfaz o núcleo de governança:
- ✅ OrchestratorContext criado e versionado (crit. 3)
- ✅ ContextPatch produzido e validado/aplicado pelo ContextBus (crit. 8, 9)
- ✅ ADR registrada (crit. 10)
- ✅ Quality gate executado (crit. 11)
- ✅ Snapshot gerado (crit. 12)
- ✅ Logs/eventos básicos (crit. 15 — parcial)

Pendentes (próximos cards F5): orquestração criável + ExecutionPlan (crit. 1, 2), Kanban runtime (crit. 4), decisão single/multi (crit. 5, 6), executor mock (crit. 7), timeline/API/CLI (crit. 13, 14).

## Restante da F5 (backlog)

`TASK-04` Kanban runtime · `TASK-05` ExecutionPlan · `TASK-06` MultiAgentDecisionEngine · `TASK-07` AgentRegistry · `TASK-08` AgentExecutor mock · `TASK-13` API mínima · `TASK-14` CLI mínima · `TASK-15` observabilidade+docs.

**Gate F5→F6 só será avaliado quando o restante do MVP-1 estiver implementado.**

## Como rodar

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q            # 24 testes
ruff check src tests
mypy src
```
