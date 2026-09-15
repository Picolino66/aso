# MEL-17 — Decidir e aplicar o congelamento de snapshots

| Campo | Valor |
|---|---|
| Fase do roadmap | 2 — Correção |
| Prioridade | P1 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-16 |
| Origem | [feedback.md](../feedback.md) §2 item 6, §7, §14 experimento 4 |
| Requer ADR | **Sim**: supersede ou reafirma ADR-0003 no que diz respeito a congelamento e ADRs com `locked_paths` |

## Problema

- `SnapshotEngine.create` sempre recebe `frozen_sections=[]` ([orchestration_service.py:6486](../src/aso/control/orchestration_service.py#L6486)).
- `ADR.locked_paths` nunca é preenchido em nenhum ponto do código.
- Logo, `ConflictDetector.check_snapshot_lock` e `check_adr_contradiction` nunca
  bloqueiam nada no uso real, embora a documentação ([snapshots.md](../docs/snapshots.md),
  [context.md](../docs/context.md)) descreva o bloqueio como garantia.
- O snapshot da mesma fase é **duplicado** na lista `b.snapshots` a cada gate aprovado
  (executado: `['O1', 'O6', 'O5', 'O5']`).
- `rollback()` ([:2924](../src/aso/control/orchestration_service.py#L2924)) restaura só o
  payload do ledger, e o nome sugere reverter código.

## Mudança proposta

**Decisão a registrar na ADR (escolher uma):**

- **Opção A — implementar:** mapa declarado fase → seções congeladas
  (ex.: F2 → `architecture`, F3 → `contracts`), aplicado no snapshot; ADRs criadas pelo
  planejamento podem declarar `locked_paths`; escrita em seção congelada exige ADR de
  override + aprovação humana.
- **Opção B — remover:** retirar `frozen_sections`, `check_snapshot_lock`,
  `check_adr_contradiction` e `locked_paths` do código e da documentação, assumindo o
  ContextBus como ledger auditável sem bloqueio.

**Independente da opção:**

1. Recriar o snapshot de uma fase **substitui** o anterior (ou gera `O5.2`), sem duplicar.
2. Renomear `rollback` de orquestração para `restaurar_ledger` na API/CLI (mantendo alias
   por uma versão) e documentar que não reverte código nem board.

## Recomendação da revisão

Opção A **somente** se MEL-19 (contexto consumido pelos agentes) for aprovada; sem
agentes lendo o contexto, congelar seções não protege nada. Caso contrário, Opção B.

## Critérios de aceite

- [ ] ADR aceita com a opção escolhida e consequências.
- [ ] Opção A: patch em seção congelada sem ADR de override é rejeitado com `SNAPSHOT_LOCK_CONFLICT` num fluxo real (não só em teste unitário do detector).
- [ ] Opção B: nenhum símbolo de congelamento restante; docs atualizadas.
- [ ] Rodar o gate da mesma fase duas vezes não duplica snapshots.
- [ ] `restaurar_ledger` documentado com o limite do que restaura.

## Testes obrigatórios

- Integração do fluxo gate → snapshot → tentativa de escrita (Opção A).
- Unit: snapshot sem duplicação.
- Regressão de `test_snapshot_engine.py`, `test_snapshot_advanced.py`, `test_contextbus.py`.

## Arquivos prováveis

- `src/aso/governance/snapshot_engine.py`, `conflict_detector.py`, `contextbus.py`, `models.py`
- `src/aso/control/orchestration_service.py` (`run_quality_gate`, `rollback`)
- `src/aso/api/app.py`, `src/aso/cli/main.py`
- `docs/snapshots.md`, `docs/context.md`
