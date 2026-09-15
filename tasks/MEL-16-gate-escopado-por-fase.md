# MEL-16 — Quality gate escopado por fase, sem aprovação vazia

| Campo | Valor |
|---|---|
| Fase do roadmap | 2 — Correção |
| Prioridade | P1 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-10 |
| Origem | [feedback.md](../feedback.md) §2 item 7, §14 experimentos 2 e 3 |
| Regra inviolável | 3 |
| Requer ADR | Sim: semântica de gate por fase e status `SKIPPED` (referencia ADR-0022, ADR-0048) |

## Problema

Em `run_quality_gate` ([orchestration_service.py:6372](../src/aso/control/orchestration_service.py#L6372)):

- O critério `context_has_output` é `b.store.version > 0 or not has_work` ([:6385](../src/aso/control/orchestration_service.py#L6385)).
  - `store.version > 0` é **global**: qualquer patch em qualquer fase aprova todas as outras.
  - `not has_work` aprova fase sem cards ("vacuamente ok").
- Resultado executado: gate de F1 sem trabalho = PASSED; gate de F6 sem nenhum card em F6 = PASSED.
- Como consequência, F1–F4 no caminho padrão viram quatro aprovações humanas de fases vazias.
- Os critérios são montados dentro do método a cada chamada: não há um lugar que declare "o que F3 exige".

## Mudança proposta

1. **Definições de gate declaradas por fase** em um módulo (`governance/gate_definitions.py`),
   cada critério como função `(estado da orquestração, fase) -> (ok, evidência)`. O
   `run_quality_gate` só monta a lista a partir dessas definições.
2. **Critério de saída por fase**: todos os cards da fase em estado terminal esperado
   (`Done`, ou `Testing` quando a fase não tem entrega por PR) **e** ao menos um patch
   aplicado com `phase == fase`.
3. **Fase sem trabalho**: novo `GateStatus.SKIPPED` com evidência "fase sem cards".
   - `SKIPPED` não gera snapshot nem aprovação `fase_gate`; o autopilot avança direto
     registrando `PhaseSkipped`.
   - `advance_phase` (MEL-10) aceita `PASSED` ou `SKIPPED`.
4. Manter os critérios condicionais já existentes (discovery aprovado em F1, deploy em
   F6, bateria de validações e docs drift em F5/F6) migrados para as definições.

## Fora de escopo

- Congelamento de seções no snapshot (MEL-17).
- Novas regras de negócio para F2/F3/F4 além de "cards da fase entregues".

## Critérios de aceite

- [ ] Um patch aplicado em F5 não aprova o gate de F2.
- [ ] Fase sem cards resulta em `SKIPPED`, sem snapshot e sem aprovação humana; a timeline mostra `PhaseSkipped`.
- [ ] Fase com card ainda em `Ready` resulta em `FAILED` com o card listado na evidência.
- [ ] Critérios de discovery, deploy, bateria de validações e docs drift mantêm o comportamento atual.
- [ ] O console mostra `SKIPPED` de forma distinta de `PASSED`.
- [ ] Os gates por fase estão documentados numa tabela gerada a partir das definições.

## Testes obrigatórios

- Unit por fase: sem cards → SKIPPED; card pendente → FAILED; tudo entregue → PASSED.
- Unit: patch de outra fase não aprova.
- Integração do autopilot: fases vazias são puladas sem aprovação.
- Regressão: `test_quality_gate_engine.py`, `test_governance_flow.py`, `test_autopilot_loop.py`.

## Arquivos prováveis

- `src/aso/governance/gate_definitions.py` (novo), `src/aso/governance/quality_gate_engine.py`
- `src/aso/shared/types.py` (`GateStatus`)
- `src/aso/control/orchestration_service.py` (`run_quality_gate`, `run_phase`, `_advance_after_phase_gate`)
- `src/aso/control/next_step.py`, console (`detalhe.html`)
- `docs/quality-gates.md`

## Riscos

- Muitos testes assumem aprovação vazia; revisar um a um em vez de relaxar o critério.
