# ADR-0074 — Execução em lote por ondas com limite de paralelismo por orquestração

- **Status:** ACCEPTED
- **Fase:** F5 (escala — MEL-50, origem `feedback.md` §3, §4)
- **Data:** 2026-09-15
- **Relaciona-se com:** [ADR-0067](ADR-0067-execucao-assincrona-com-fila.md) (fila de jobs),
  [ADR-0058](ADR-0058-claim-de-execucao-do-card.md) (claim),
  [ADR-0071](ADR-0071-retry-unico-pelo-roteamento-de-falha.md) (retry pelo roteamento),
  [ADR-0030](ADR-0030-checklist-de-preparacao.md) (dependências do card)

## Contexto

`run_phase` executava os cards da fase em sequência; `run_plan` tinha um laço próprio de ondas que
chamava o provider sem o roteamento de falha do `run_card` e contava como "dependência satisfeita" um
card apenas executado (ainda em `Testing`); a estratégia `parallel_agents` do motor de decisão não
mudava nada na execução.

## Decisão

1. **Coordenador único** (`application/ondas.py::CoordenadorDeOndas`) usado por `run_phase` e
   `run_plan`: onda = cards `Ready` cujas dependências estão **`Done`**; cada card roda pelo
   `run_card` (claim, guards, roteamento de falha).
2. **Dependência pendente não entra na onda:** o card fica `Ready` e aparece em
   `aguardando_dependencia` (evento `CardsAguardandoDependencia` na fase). Não é mais bloqueado por
   uma tentativa às cegas; o `run_card` manual continua bloqueando e criando a tarefa vinculada
   (ADR-0030).
3. **Limite por orquestração pela estratégia:** `parallel_agents` executa até
   `ASO_MAX_PARALELO_POR_ORQUESTRACAO` (padrão 2) cards ao mesmo tempo; todas as demais estratégias
   (e `run_plan(concurrent=False)`), um por vez.
4. **Limite global** de execuções simultâneas no processo: `ASO_MAX_EXECUCOES_SIMULTANEAS`
   (padrão 4), somado aos workers da fila.
5. As threads da onda recebem o contexto copiado (cancelamento de job e `request_id`).

## Consequências

- Dependentes na mesma fase não rodam na mesma execução em que a dependência foi feita: esperam o
  merge/QA levá-la a `Done` e uma nova execução (autopilot, run-plan ou run-phase).
- `run_plan` passa a devolver `paralelismo` e `aguardando_dependencia`; `waves` conta só as ondas
  efetivamente executadas.
- Sub-jobs por card na fila (em vez de threads dentro do job da fase) seguem fora de escopo — o
  claim e os limites já impedem execução dupla e excesso de concorrência.
