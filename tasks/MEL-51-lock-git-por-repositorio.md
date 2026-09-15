# MEL-51 — Lock git por repositório

| Campo | Valor |
|---|---|
| Fase do roadmap | 5 — Escala |
| Prioridade | P2 |
| Esforço | baixo |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §3 (escalabilidade) |
| Requer ADR | Não |

## Problema

`_GIT_META_LOCK` ([worktree.py:18](../src/aso/execution/worktree.py#L18)) é um único
`threading.Lock` global do módulo. Ele serializa **todas** as operações git
(`worktree add/remove`, `add`, `commit`, `diff`, `merge`) de **todos** os repositórios-alvo,
inclusive leituras como `branch_diff`, `changed_files` e `line_stats`, e o `git add -A` +
`diff` de `collect_diff`. Orquestrações de projetos diferentes esperam umas pelas outras.

## Mudança proposta

1. Registro de locks por caminho resolvido do repositório base (`dict[str, Lock]` protegido por um lock de registro).
2. Leituras que não tocam índice/refs compartilhados (`diff HEAD...branch`, `rev-list`) sem lock
   ou com lock de leitura, se o teste de estresse confirmar segurança.
3. Manter o lock para `worktree add/remove`, `merge` e `commit`.

## Critérios de aceite

- [ ] Operações em dois repositórios distintos ocorrem em paralelo (teste com medição de sobreposição).
- [ ] `test_race_stress.py`, `test_candidates.py` e `test_worktree_diff.py` verdes.
