# ADR-0061 — Congelamento de seções por snapshot (reafirma ADR-0003) e `restaurar_ledger`

- **Status:** ACCEPTED
- **Fase:** F5 (correção de governança — MEL-17, origem `feedback.md` §2 item 6, §7, §14 exp. 4)
- **Data:** 2026-09-15
- **Relaciona-se com:** [ADR-0003](ADR-0003-contextbus-governance.md) (reafirmada: "snapshots
  congelam seções; escrita em seção congelada exige ADR de override"),
  [ADR-0060](ADR-0060-gate-escopado-por-fase.md) (snapshot só em gate `PASSED`)

## Contexto

A ADR-0003, o `docs/snapshots.md` e o `docs/context.md` descrevem o congelamento como
garantia, mas o código nunca o aplicava:

- `SnapshotEngine.create` recebia sempre `frozen_sections=[]`;
- `ADR.locked_paths` nunca era preenchido;
- logo `ConflictDetector.check_snapshot_lock` e `check_adr_contradiction` nunca bloqueavam
  nada no uso real;
- a lista de snapshots da orquestração duplicava a versão a cada gate aprovado
  (`['O1', 'O6', 'O5', 'O5']`);
- `rollback` restaurava só o payload do ledger, mas o nome sugeria reverter código.

A revisão propôs escolher entre **A (implementar)** e **B (remover)**, recomendando A só se
o contexto passar a ser consumido pelos agentes (MEL-19).

## Opções consideradas

- **B — remover** `frozen_sections`, `check_snapshot_lock`, `check_adr_contradiction`,
  `locked_paths` e a documentação. Honesto com o estado atual, mas retira uma garantia de
  governança declarada no CLAUDE.md e na ADR-0003 sem task que a substitua.
- **A — implementar** com mapa declarado por fase. Adotada: a MEL-19 (contexto injetado nos
  providers) está no backlog aprovado, e o congelamento já protege hoje as escritas via
  ContextBus (API `context-patches` e patches de agentes).

## Decisão

1. **Mapa fase → seções congeladas** em `governance/snapshot_engine.py`
   (`SECOES_CONGELADAS_POR_FASE`): F1 → `product`, `market`, `business`, `requirements`,
   `scope`, `feasibility`; F2 → `architecture`; F3 → `contracts`; F4 → `ux`; F5–F7 → nenhuma
   (engenharia, qualidade e operação são trabalho contínuo). Aplicado por
   `run_quality_gate` ao criar o snapshot da fase.
2. **Override** de seção congelada exige **ADR aceita referenciada** (`requires_adr` +
   `linked_adrs`) **e aprovação humana**: a etapa *snapshot lock* do ContextBus marca o patch
   como `requires_approval`, que vira `HumanApproval tipo=patch` (admin). Sem override →
   `SNAPSHOT_LOCK_CONFLICT`.
3. **`locked_paths`**: ADRs do planejamento (`PlannedAdr.locked_paths`, também no schema do
   prompt) são registradas com os caminhos governados; escrever neles sem referenciar a ADR
   é rejeitado (`ARCHITECTURE_CONFLICT`). Persistido (tabela de relação existente).
4. **Sem duplicação:** recriar o snapshot de uma fase substitui o anterior da mesma versão.
5. **`restaurar_ledger`** substitui `rollback` no serviço, na API
   (`POST .../restaurar-ledger`, admin) e na CLI (`aso restaurar-ledger`). `rollback` fica
   como alias obsoleto por uma versão. Restaura **só** o `OrchestratorContext` (payload +
   seções congeladas) e registra ADR — não reverte código, branches, board, aprovações
   nem implantações.

## Consequências

- Reexecutar o agente de uma fase já congelada bloqueia o card (conflito) até existir ADR de
  override aprovada — mudar decisão consolidada passa a ser decisão registrada.
- `restore_section` (admin + ADR) continua sendo o bypass governado para restaurar uma seção.
- Com múltiplas iterações de uma mesma fase o snapshot mais recente vale; a trilha dos
  anteriores fica nos eventos `SnapshotCreated`.
- O alias `rollback` deve ser removido na próxima versão (MEL-53).
