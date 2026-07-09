# ADR-0009 — Entrega de código somente com evidência verificável

- **Status:** ACCEPTED
- **Fase:** F5
- **Data:** 2026-07-09
- **Supersede parcialmente:** ADR-0007 (ciclo de autopilot) e ADR-0008 (workspace)

## Contexto

Uma execução CLI com `exit != 0` ou sem diff era tratada como sucesso. O gate podia
aprovar F5 antes de uma PR ser validada e mesclada, deixando o workspace sem código.

## Decisão

Para orquestrações novas configuradas no console, execução de código exige diff não
vazio e comando de validação. O card aguarda PR, CI na branch, revisão humana e merge
governado antes do gate da fase. O merge usa sempre o workspace da orquestração.

## Consequências

- Não há aprovação de fase enquanto houver entrega pendente.
- Falha do agente e diff vazio bloqueiam o card com motivo rastreável.
- Execução direta começa em F5; pipeline completo requer planejamento LLM.
