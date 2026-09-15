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

- Criar snapshot; comparar snapshots; restaurar o ledger a um snapshot.
- **Bloquear alteração direta de seção congelada** (`frozen_sections`).
- Exigir **ADR + aprovação humana** para override de seção congelada.

### Seções congeladas por fase (ADR-0061)

Declaradas em `SECOES_CONGELADAS_POR_FASE` (`src/aso/governance/snapshot_engine.py`) e
aplicadas pelo `run_quality_gate` quando o gate da fase é `PASSED`:

| Snapshot | Seções congeladas |
|---|---|
| O1 (F1) | `product`, `market`, `business`, `requirements`, `scope`, `feasibility` |
| O2 (F2) | `architecture` |
| O3 (F3) | `contracts` |
| O4 (F4) | `ux` |
| O5–O7 (F5–F7) | nenhuma (trabalho contínuo) |

- Escrita sem override → rejeitada com `SNAPSHOT_LOCK_CONFLICT`.
- Override (`requires_adr` + `linked_adrs` com ADR aceita) → patch **pendente** de
  aprovação humana (admin); só então é aplicado.
- ADRs com `locked_paths` (ex.: do planejamento) travam caminhos específicos: escrever neles
  exige referenciar a ADR.
- Rodar o gate da mesma fase de novo **substitui** o snapshot daquela versão (não duplica).
- `POST .../restaurar-ledger` (admin; `rollback` é alias obsoleto) restaura **só o ledger do
  contexto** — payload e seções congeladas do snapshot — e registra ADR. Não reverte código,
  branches, board, aprovações nem implantações.

O bloqueio de seções congeladas é aplicado pelo `ContextBus` na etapa 4 da validação (*snapshot lock validation*) — ver [`context.md`](context.md).

## 2. Estado do processo de construção do ASO

A tabela "O1–O4 existentes" que existia aqui descrevia o **processo de construção do próprio
ASO** (arquivos em `.aso/snapshots/`), não o estado do runtime. Os snapshots de uma
orquestração vêm de `GET /v1/orchestrations/{id}/snapshots`. A separação dos artefatos de
construção é a MEL-04 (aguardando decisão do operador).

## Referências

- Quality gates: [`quality-gates.md`](quality-gates.md)
- Governança de contexto: [`context.md`](context.md)
- Requisitos: [`requerimentos.md` §23](../requerimentos.md)
