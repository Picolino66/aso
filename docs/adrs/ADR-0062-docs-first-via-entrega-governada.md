# ADR-0062 — Docs-first e self-heal via entrega governada

- **Status:** ACCEPTED
- **Fase:** F5 (correção de governança — MEL-18, origem `feedback.md` §2 item 10)
- **Data:** 2026-09-15
- **Supersede parcialmente:** [ADR-0008](ADR-0008-workspace-por-orquestracao.md) (trecho
  "diff mesclado … **sem** aprovação humana (docs = baixo risco)") e ajusta
  [ADR-0012](ADR-0012-drift-check-docs-first.md) (self-heal "com o diff mesclado")
- **Relaciona-se com:** regras invioláveis 5 e 6, [ADR-0056](ADR-0056-ci-executada-e-declarada.md)
  (CI declarada), [ADR-0060](ADR-0060-gate-escopado-por-fase.md) (gate por fase)

## Contexto

`analyze_folder` e `heal_docs` escreviam na branch base do repositório-alvo sem PR, CI nem
revisão: `commit_all` direto (scaffold, inclusive em projeto existente sem agente real) e
`WorktreeManager.merge(branch)` do diff do agente, engolindo falha com
`except WorktreeError: pass`. `_maybe_autoheal_docs` fazia o mesmo ao fim de F5/F6, sem
nenhum humano ver, e `ensure_git` inicializava git na pasta do usuário sem perguntar. A
ADR-0008 justificava com "docs = baixo risco" — mas é código de agente entrando na base,
exatamente o que as regras 5 e 6 proíbem.

## Opções consideradas

1. **Manter o merge direto só para docs.** Mantém uma exceção às regras 5/6 sem controle.
2. **Exigir aprovação humana no merge direto.** Aprovação sem diff revisável, CI e ficha.
3. **Docs como qualquer entrega: card + PR + merge governado.** Adotada.

## Decisão

- Documentação gerada (agente real ou scaffold determinístico) vai para um **branch
  isolado** e vira **card `Documentation`** (fase corrente, `DocumentationAgent`) com **PR
  interna** — CI (quando houver bateria) → revisão → merge admin, as mesmas condições de
  `merge_pr`. O scaffold sem agente real é escrito num worktree próprio
  (`docs/docs-first-<sufixo>`), commitado e o worktree removido.
- **Única exceção de commit direto:** pasta **vazia** num repositório **sem histórico**
  (um único commit `aso: init do workspace`, criado pelo próprio ASO) — não há trabalho de
  ninguém na base. A rede de segurança do scaffold só vale nesse caso.
- `heal_docs`: com agente real, a PR é do agente (recebe todos os pontos de drift); sem
  agente, PR do scaffold dos módulos sem doc. `_maybe_autoheal_docs` passa a **abrir o
  card/PR** e não abre outra enquanto houver PR de docs aberta.
- **Falha de merge nunca é silenciosa:** `merge_pr` captura o erro do git, registra
  `DocsMergeFailed` (card `Documentation`) ou `MergeFailed`, mantém PR e card abertos e
  devolve 409; `WorktreeManager.merge` aborta o merge em conflito (a base não fica em estado
  de merge pela metade). Não resta `except WorktreeError: pass` no serviço.
- **`git init` exige confirmação:** `analyze_folder`, `heal_docs` e `start_autopilot` recebem
  `inicializar_git` (corpo das rotas `analyze-folder`, `docs-heal`, `autopilot`); sem a flag,
  pasta sem git → erro claro; com a flag → `ensure_git` + evento `WorkspaceGitInitialized`.
  O console pergunta ao usuário e reenvia com a flag.
- O retorno informa `entrega` (`commit_direto` | `pr` | `sem_alteracao`), `card_id` e
  `pr_id`.

## Consequências

- A branch base só muda por merge governado — inclusive para documentação.
- O card `Documentation` na fase corrente segura o gate dela até ser mesclado (ADR-0060):
  docs pendentes aparecem como trabalho pendente, não como detalhe invisível.
- `has_aso_docs` do `analyze-folder` reflete a base: com entrega por PR, fica `false` até o
  merge.
- O `scripts/smoke.sh` confirma a inicialização de git e aceita as duas entregas.
