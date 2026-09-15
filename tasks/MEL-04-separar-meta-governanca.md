# MEL-04 — Separar a meta-governança da construção do produto

| Campo | Valor |
|---|---|
| Fase do roadmap | 1 — Clareza |
| Prioridade | P1 |
| Esforço | baixo |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §1 (onde vive o estado, item 5), §5, §7 |
| Requer ADR | Sim, curta: onde vive a governança do processo de construção do ASO |

## Problema

Dois conceitos usam os mesmos nomes e a mesma pasta:

- **Runtime do produto:** `.aso/worktrees/`, `.aso/executors.json`, `.aso/run/` — criados pelo ASO nos repositórios-alvo e localmente.
- **Processo de construção do ASO:** `.aso/context/orchestrator-context.json`,
  `.aso/kanban/board.json`, `.aso/snapshots/`, `.aso/quality-gates/`, `.aso/reviews/`,
  `specs/`, `docs/phases/`, `docs/mvp/` — mantidos à mão e **nunca lidos pelo runtime**.

Isso gera frases contraditórias ("F7 concluída" × "F5 pendente") e faz o leitor achar que
esses JSON são estado do produto.

## Mudança proposta

1. Mover os artefatos do processo de construção para `docs/historico/`:
   - `.aso/{context,kanban,snapshots,quality-gates,reviews}` → `docs/historico/governanca-construcao/`
   - `specs/` → `docs/historico/specs-mvp1/`
   - `docs/phases/`, `docs/mvp/`, `docs/plano-fidelidade-fluxo.md` → `docs/historico/`
2. Atualizar CLAUDE.md/AGENTS.md: a seção "Ao concluir, atualize a governança" passa a
   apontar para os novos caminhos (o fluxo de trabalho continua o mesmo).
3. Atualizar `scripts/reset.sh`, que hoje preserva `.aso/context|kanban|…` por nome.
4. Deixar `.aso/` só para estado de runtime (e confirmar no `.gitignore`).

## Critérios de aceite

- [ ] Nenhum arquivo do processo de construção dentro de `.aso/`.
- [ ] Links internos atualizados (verificar com busca por `.aso/context`, `.aso/kanban`, `specs/`).
- [ ] CLAUDE.md, AGENTS.md e `reset.sh` coerentes com os novos caminhos.
- [ ] Nenhum código em `src/` referencia os caminhos antigos (já não referencia hoje; manter).

## Riscos

- Muda o fluxo que o CLAUDE.md impõe aos agentes deste repositório — decisão do operador;
  confirmar antes de mover.
