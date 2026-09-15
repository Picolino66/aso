# MEL-50 — Paralelismo por onda na fila de execução

| Campo | Valor |
|---|---|
| Fase do roadmap | 5 — Escala |
| Prioridade | P2 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-31 |
| Origem | [feedback.md](../feedback.md) §3 (escalabilidade), §4 (paralelismo) |
| Requer ADR | Sim, curta: política de concorrência por orquestração |

## Problema

- `run_phase` executa os cards da fase **em sequência** (laço simples).
- `run_plan` tem paralelismo por ondas topológicas, mas usa `plan.agents` (perde cards,
  ver MEL-20), não é usado pela UI e ignora `parallel_group`.
- A estratégia `parallel_agents` escolhida pelo motor de decisão não muda nada na execução.

## Mudança proposta

1. O coordenador de fase (MEL-31) enfileira os cards cujas dependências estão `Done`
   ("onda"); ao terminar um card, libera os dependentes.
2. Limite por orquestração (`ASO_MAX_PARALELO_POR_ORQUESTRACAO`, padrão 2) e limite global de workers.
3. A estratégia do plano define o limite padrão: `single_agent`/`sequential_agents` = 1; `parallel_agents` = limite configurado.
4. Remover `run_plan` como caminho separado (endpoint mantido delegando ao coordenador).

## Critérios de aceite

- [ ] Cards independentes da mesma fase executam em paralelo até o limite.
- [ ] Card com dependência só entra na fila após a dependência chegar a `Done`.
- [ ] Estratégia sequencial executa um card por vez.
- [ ] Nenhum card é executado duas vezes (claim de MEL-13).
