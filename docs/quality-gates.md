# Quality Gates — ASO Runtime

> Explica o `QualityGateEngine` (§22) e lista os gates por fase.
> **Resultados materializados em:** [`.aso/quality-gates/`](../.aso/quality-gates/).
> Requisito: [`requerimentos.md` §22](../requerimentos.md).

## 1. QualityGateEngine (§22)

Cada fase F1–F7 tem um **quality gate** que valida critérios verificáveis antes de permitir o avanço. Regras:

- **Gate falho bloqueia o avanço** de fase.
- Gate falho pode gerar cards automáticos e acionar o agente responsável.
- Gate crítico pode exigir aprovação humana.
- **Fase aprovada gera um snapshot** (ver [`snapshots.md`](snapshots.md)).

Cada resultado (`QualityGateResult`) registra: `phase`, `status` (`PASSED`/`FAILED`/`WARNING`), lista de `criteria` (com `evidence` e `failure_reason`), `blocking_issues`, `warnings`, `required_actions`, `approved_by` e se exigiu aprovação humana.

## 2. Gates por fase e estado atual

| Fase | Gate | Estado | Snapshot gerado | Evidência |
|---|---|---|---|---|
| F1 → F2 | Discovery & Strategy | ✅ PASSED | O1 | [F1 §12](phases/F1-discovery.md) · `.aso/quality-gates/F1-gate.json` |
| F2 → F3 | Architecture & Design | ✅ PASSED | O2 | [F2 §12](phases/F2-architecture.md) · `.aso/quality-gates/F2-gate.json` |
| F3 → F4 | Data & API Contracts | ✅ PASSED | O3 | [F3 §8](phases/F3-contracts.md) · `.aso/quality-gates/F3-gate.json` |
| F4 → F5 | UX/UI & Planning | ✅ PASSED | O4 | [F4 §8](phases/F4-planning.md) |
| F5 → F6 | Engineering Execution | ⏳ pendente | O5 | — |
| F6 → F7 | Quality, Docs & Deploy | ⏳ pendente | O6 | — |
| F7 | Operate & Evolve | ⏳ pendente | O7 | — |

**Estado atual: gates F1–F4 PASSED.** Os resultados JSON de F1–F3 estão em [`.aso/quality-gates/`](../.aso/quality-gates/); o gate F4→F5 está registrado em [F4 §8](phases/F4-planning.md) (snapshot O4). A próxima fase é F5 (Engineering Execution).

## Referências

- Snapshots: [`snapshots.md`](snapshots.md)
- Governança de contexto: [`context.md`](context.md)
- Requisitos: [`requerimentos.md` §22](../requerimentos.md)
