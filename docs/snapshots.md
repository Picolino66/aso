# Snapshots — ASO Runtime

> Explica o `SnapshotEngine` (§23) e lista os snapshots O1–O7.
> **Snapshots materializados em:** [`.aso/snapshots/`](../.aso/snapshots/).
> Requisito: [`requerimentos.md` §23](../requerimentos.md).

## 1. SnapshotEngine (§23)

Um snapshot é gerado **após cada fase aprovada pelo quality gate**, congelando o estado do `OrchestratorContext` para garantir imutabilidade e permitir rollback. Snapshots obrigatórios:

```
O1 após F1   O2 após F2   O3 após F3   O4 após F4   O5 após F5   O6 após F6   O7 após F7
```

Cada snapshot (`Snapshot`) registra: `snapshot_version`, `phase`, `context_hash`, `frozen_sections`, `quality_gate_result_id`, `adrs` e `cards`.

### Funcionalidades

- Criar snapshot; comparar snapshots; restaurar snapshot.
- **Bloquear alteração direta de seção congelada** (`frozen_sections`).
- Exigir **ADR + aprovação humana** para override de seção congelada.

O bloqueio de seções congeladas é aplicado pelo `ContextBus` na etapa 4 da validação (*snapshot lock validation*) — ver [`context.md`](context.md).

## 2. Snapshots existentes

| Snapshot | Fase | Seções congeladas | Gate | Artefato |
|---|---|---|---|---|
| O1 | F1 | discovery/product/scope | gate-F1 | [`.aso/snapshots/O1.json`](../.aso/snapshots/O1.json) |
| O2 | F2 | architecture | gate-F2 | [`.aso/snapshots/O2.json`](../.aso/snapshots/O2.json) |
| O3 | F3 | contracts | gate-F3-0001 | [`.aso/snapshots/O3.json`](../.aso/snapshots/O3.json) |
| O4 | F4 | ux/planning | gate-F4 | ver [F4 §8](phases/F4-planning.md) |
| O5–O7 | F5–F7 | — | ⏳ pendente | — |

**Estado atual: snapshots O1–O4.** Os artefatos JSON de O1–O3 estão em [`.aso/snapshots/`](../.aso/snapshots/); O4 acompanha a conclusão de F4, documentada em [F4 §8](phases/F4-planning.md).

## Referências

- Quality gates: [`quality-gates.md`](quality-gates.md)
- Governança de contexto: [`context.md`](context.md)
- Requisitos: [`requerimentos.md` §23](../requerimentos.md)
