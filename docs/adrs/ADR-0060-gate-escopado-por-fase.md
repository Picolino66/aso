# ADR-0060 — Quality gate escopado por fase e status `SKIPPED`

- **Status:** ACCEPTED
- **Fase:** F5 (correção de governança — MEL-16, origem `feedback.md` §2 item 7, §14 exp. 2 e 3)
- **Data:** 2026-09-15
- **Relaciona-se com:** [ADR-0022](ADR-0022-bateria-de-validacoes-e-effort-automatico.md)
  (bateria de validações no gate de F5/F6), [ADR-0048](ADR-0048-execucao-quality-gates-e-falhas.md)
  (evidência e duração por critério), ADR-0020/ADR-0023/ADR-0029 (critérios condicionais de
  discovery e implantação), regra inviolável 3 (MEL-10, `advance_phase`)

## Contexto

O critério de saída de todo gate era `store.version > 0 or not has_work`:

- `store.version` é **global** — um patch aplicado em F5 aprovava o gate de F2;
- `not has_work` aprovava fase sem cards ("vacuamente ok") — o gate de F6 sem nenhum card
  em F6 dava `PASSED`, gerava snapshot e abria aprovação humana de avanço.

No caminho padrão (cards só em F5), F1–F4 viravam quatro aprovações humanas de fases
vazias — ruído que ensina o operador a aprovar sem olhar. E os critérios eram montados
inline em `run_quality_gate`: não havia um lugar declarando o que cada fase exige.

## Opções consideradas

1. **Só trocar `store.version` por contagem de patches da fase.** Corrige o vazamento entre
   fases, mas mantém a aprovação vazia e os critérios implícitos.
2. **Fase sem cards = `FAILED`.** Travaria toda esteira que não usa todas as fases.
3. **Definições declarativas por fase + `SKIPPED` para "nada bloqueante a verificar".**
   Adotada.

## Decisão

- `governance/gate_definitions.py` declara cada critério uma vez (nome, fases, descrição,
  bloqueante, gerador). A camada de controle monta um retrato de dados (`EstadoDoGate`) e
  passa funções prontas para o que depende de I/O (bateria, drift de docs) — o módulo não
  importa `aso.control` (regra de dependência).
- Critérios por fase (tabela gerada em `docs/quality-gates.md` por `tabela_markdown()`,
  com teste que falha se divergir):
  - `cards_da_fase_entregues` (todas): card da fase `Done`, ou `Testing` **sem branch**
    (fase sem entrega por PR); `Cancelled`/`Archived` ficam fora; a evidência lista os
    pendentes;
  - `output_da_fase_aplicado` (todas, quando há cards): ≥ 1 `ContextPatch` aplicado com
    `phase` igual à do gate — substitui `context_has_output` global;
  - mantidos: `discovery_aprovado` (F1), `deploy_aprovado` (F6), bateria de validações e
    `docs_in_sync` não bloqueante (F5/F6); `cards_entregues` (merge governado com validação
    configurada) passa a exigir cards na fase.
- `GateStatus.SKIPPED`: quando **nenhum critério bloqueante** se aplica. Os não
  bloqueantes ainda rodam e viram warnings. `SKIPPED` não gera snapshot, não abre
  aprovação `fase_gate` e `approved_by` fica vazio.
- `advance_phase` aceita o último gate `PASSED` **ou** `SKIPPED` (um `FAILED` posterior
  continua bloqueando). `run_phase` registra `PhaseSkipped`; no autopilot
  (`start_autopilot`/auto-avanço) avança e roda a próxima fase direto, devolvendo
  `fases_puladas`. `next_step` trata `SKIPPED` como gate liberado.
- Continuam exigindo `PASSED` estrito: criação de snapshot e "testes aprovados" da
  implantação (§18) — pular não é testar.
- A CLI `aso run` avalia o gate de cada fase que recebeu cards, não da fase corrente vazia.
- Status é `String` no banco: sem migration.

## Consequências

- Uma fase só é aprovada pelo que aconteceu nela; fases vazias deixam de pedir aprovação
  humana, e o autopilot para apenas em gates com trabalho real.
- Testes e fixtures que dependiam da aprovação vazia foram revistos um a um: os de
  implantação passaram a configurar uma verificação real (`validation_command="true"`)
  para ter `PASSED` de verdade; os de snapshot usam duas fases com trabalho (F2 e F5).
- O congelamento de seções no snapshot (`frozen_sections=[]`) segue fora (MEL-17).
- Console (`index.html`, `card-detalhe.html`, `testes.html`) mostra `SKIPPED` com estilo
  próprio (`pill info`), distinto de `PASSED`.
