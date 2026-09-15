# MEL-34 — Suíte de testes negativos de governança via API

| Campo | Valor |
|---|---|
| Fase do roadmap | 3 — Robustez |
| Prioridade | P1 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-10, MEL-11, MEL-12, MEL-13, MEL-14, MEL-15 |
| Origem | [feedback.md](../feedback.md) §6 (sem testes), §13.4 melhoria 1 |
| Requer ADR | Não |

## Problema

Os 1.356 testes cobrem bem o caminho feliz e as funções puras, mas não havia nenhum teste
que **tentasse** violar as regras invioláveis pela API. Por isso os bypasses (avanço sem
gate, estratégia crítica sem aprovação, CI declarada, execução duplicada) passaram
despercebidos.

## Mudança proposta

Criar `tests/integration/test_governanca_invariantes.py`, com `AuthService` configurado
com chaves reais (viewer, operator, admin), contendo ao menos um teste por regra:

| Regra | Tentativa de violação | Esperado |
|---|---|---|
| 1 ContextBus único escritor | Mutar contexto por rota que não passa pelo bus | Nenhuma rota permite |
| 2 Deny-by-default | Patch com `agent` sem permissão na seção | `rejected` + conflito |
| 3 Gate | `advance-phase` sem gate / com gate FAILED | 409 |
| 4 Aprovação crítica | Executar card com estratégia pendente | 409, 0 chamadas ao provider |
| 4 Papel admin | Operator em merge, aprovação, rollback, CI declarada, comandos de host | 403 |
| 5 Worktree isolado | Execução de card / docs-first | HEAD da branch base inalterado até o merge |
| 6 Merge governado | Merge sem CI executada, sem review aprovada, com comentário obrigatório pendente | 409 |
| — Execução única | Duas execuções concorrentes do mesmo card | 1 execução |
| 9 Secrets | Registro de execução com valor de chave | Não persistido |

Marcar o arquivo como obrigatório no CI (falha bloqueia merge) e referenciar cada teste na
tabela do `docs/GOVERNANCE.md` (MEL-01).

## Critérios de aceite

- [ ] Todos os testes da tabela existem e passam após as tasks P0.
- [ ] Reverter qualquer uma das correções P0 faz ao menos um teste falhar (verificado manualmente uma vez por regra).
- [ ] `docs/GOVERNANCE.md` aponta para cada teste.
