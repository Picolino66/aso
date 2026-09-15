# ADR-0071 — Retry único: o roteamento de falha é a única camada de nova tentativa

- **Status:** ACCEPTED
- **Fase:** F5 (robustez — MEL-35, origem `feedback.md` §1, §3)
- **Data:** 2026-09-15
- **Atualiza:** [ADR-0019](ADR-0019-roteamento-de-falha.md) — a camada responsável por retry
- **Relaciona-se com:** [ADR-0014](ADR-0014-agente-por-etapa-e-nomes-semanticos.md) (nomes
  semânticos), [ADR-0059](ADR-0059-contrato-task-envelope.md) (o `nudge` do supervisor não chegava
  ao CLI)

## Contexto

Havia duas camadas de retry sobrepostas: `AgentSupervisor` (`max_attempts=2`, re-tentava qualquer
exceção com um `nudge` genérico) e o laço de `run_card` guiado por `failure.decidir` (mesmo
agente, mais esforço, outro executor). Cada falha podia virar até 2 × 3 execuções, cada uma com
worktree novo e timeout longo; o supervisor re-tentava até timeout, que o roteamento trataria de
outro jeito, e o diagnóstico recebia "falhou após 2 tentativas: …" em vez do erro real. Com
agente de nomeação configurado, cada tentativa ainda perguntava os nomes de novo.

## Decisão

1. `AgentSupervisor` faz **uma** tentativa por padrão; ao falhar, levanta `AgentExecutionError`
   com a **mensagem original** (exceção encadeada). `max_attempts > 1` continua possível para uso
   isolado, mas o runtime não usa.
2. Toda nova chamada ao provider vem de uma decisão do roteamento; o laço do `run_card` registra
   `AgentRetry` (com `acao` e `error`) a cada decisão de nova tentativa — a métrica
   `retries`/`aso_agent_retries_total` passa a contar essas decisões.
3. Os nomes do card (`branch_stem`, `commit_subject`) são calculados na primeira execução e
   guardados no card (colunas em `kanban_cards`); tentativas, novas execuções e corridas reusam.

## Consequências

- Falha de execução = exatamente uma chamada ao provider por decisão do roteamento; o painel do
  agente e o `agent_runs` mostram uma sessão por tentativa real.
- `agent_executions` e `failures` contam a tentativa que falhou (antes o supervisor a escondia).
- Mudar o título do card depois da primeira execução não renomeia a branch (estável por card).
