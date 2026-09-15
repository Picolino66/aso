# MEL-35 — Retry único via roteamento de falha

| Campo | Valor |
|---|---|
| Fase do roadmap | 3 — Robustez |
| Prioridade | P2 |
| Esforço | baixo |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §1 (retry aninhado), §3 (custo) |
| Requer ADR | Sim, curta: atualiza ADR-0019 sobre a camada responsável por retry |

## Problema

Existem duas camadas de retry sobrepostas:

1. `AgentSupervisor` com `max_attempts=2` ([supervisor.py:22](../src/aso/agents/supervisor.py#L22)), que re-tenta **qualquer** exceção com um `nudge` genérico;
2. o laço de `run_card`, guiado por `failure.decidir` (mesmo agente, mais effort, trocar executor), até `max_tentativas`.

Cada falha pode gerar até 2 × 3 execuções, cada uma com worktree novo e timeout de 1.800 s.
O supervisor re-tenta até timeout, que o roteamento trataria de outra forma. O `nudge`
do supervisor nem chega ao agente CLI (ver MEL-14).

Além disso, com agente de nomeação configurado, `_build_task` chama o agente a cada
tentativa ([:5547](../src/aso/control/orchestration_service.py#L5547)).

## Mudança proposta

1. `AgentSupervisor` com 1 tentativa por padrão (ou removido; o roteamento assume a decisão).
2. O diagnóstico do roteamento recebe o erro original (sem o prefixo "falhou após N tentativas").
3. Nomeação calculada uma vez por card e reaproveitada nas tentativas (guardar em `card.branch_stem`/`commit_subject`).

## Critérios de aceite

- [ ] Falha de execução gera exatamente uma chamada ao provider por decisão do roteamento.
- [ ] O agente de nomeação é chamado no máximo uma vez por card.
- [ ] Testes de roteamento de falha continuam cobrindo mesmo agente, effort e troca de executor.
