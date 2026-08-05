# ADR-0027 — Sobrevivência a crash de processo

- **Status:** ACCEPTED
- **Fase:** F5/F7
- **Data:** 2026-08-04
- **Relaciona-se com:** [ADR-0014](ADR-0014-agente-por-etapa-e-nomes-semanticos.md)
  (`WorktreeManager`, quem cria/remove worktrees), [ADR-0019](ADR-0019-roteamento-de-falha.md)
  (`route_card`, reaproveitado sem caminho novo de recuperação), [`scripts/reset.sh`](../../scripts/reset.sh)
  (precedente do "nunca `rm -rf` num worktree"), [`fluxo.md`](../../fluxo.md) §14,
  [`plano7.md`](../../plano7.md) §1.4, §3.3

## Contexto

Duas lacunas que só aparecem quando o processo da API morre no meio de uma
execução (deploy, `Ctrl-C`, OOM) — nunca quando tudo roda até o fim:

**Card preso em `InProgress`.** `next_step.py` já cobre `Blocked`, `Failed`,
`NeedsFix`, mas não havia nenhum tratamento de `IN_PROGRESS`. A tela mostra
um card "trabalhando" que não tem ninguém trabalhando nele, e o operador não
recebe ação nenhuma.

**Worktree órfão.** `CliAgentExecutionProvider.execute` remove o worktree num
`finally`, mas um processo morto não roda `finally`. A única ferramenta que
limpava worktrees órfãos era [`scripts/reset.sh`](../../scripts/reset.sh) —
que também apaga o banco inteiro. Não existia caminho para "limpe o lixo sem
perder o trabalho".

## Decisão

### 1. Card órfão — `next_step.py::_orphan_card_blocker`

Não existe forma confiável de saber, de dentro de um processo novo, se o
processo antigo morreu de verdade (não há supervisor nem heartbeat — inventar
um seria maior que o problema). O sinal usado é o que já existe:
`card.updated_at` parado há mais tempo que `ASO_AGENT_TIMEOUT`
(`cli_provider.TIMEOUT_PADRAO`, default 1800s) — o próprio timeout já
garante que nenhum agente vivo poderia ainda estar naquele card (o provider
mata e move o card para fora de `InProgress` antes de estourar esse tempo em
qualquer execução que continue viva).

Bloqueio `card_orfao` (`acao_do_operador`) aponta para `POST
.../cards/{id}/route` — **reaproveita `route_card`**, que já existe desde o
Incremento C (a política de roteamento de falha da ADR-0019 decide o
retorno); nenhum caminho novo de recuperação foi criado.
`NextStepInput.agent_timeout_seconds`/`gasto_usd` chegam pelo
`OrchestrationService.next_step`, coletados uma vez por chamada — o motor
continua puro (sem I/O), mesmo arranjo de todo outro bloqueio.

### 2. Worktree órfão — `WorktreeManager.list_worktrees`/`prune`

`git worktree list --porcelain` é a fonte de verdade (a mesma que
`scripts/reset.sh` já usava) — não uma varredura de diretório, que veria
pasta órfã sem entrada git ou entrada git sem pasta. Filtra o que está sob
`.aso/worktrees/` do repositório da orquestração.

Um worktree é órfão quando **nenhum card ativo** (fora de
`Done`/`Cancelled`/`Archived`) o referencia por `branch` ou `worktree`
(`OrchestrationService._branches_ativas`). `prune` sempre usa `git worktree
remove --force` seguido de `git worktree prune` — **nunca `rm -rf`**, que
deixaria referências penduradas em `.git/worktrees` (o motivo pelo qual
`reset.sh` já fazia assim).

API: `GET .../worktrees` (viewer) sempre devolve a lista **completa**, com
`orfao` marcado — nunca só os órfãos, para o operador ver o que está ativo
antes de confiar no que não está (mesmo padrão de
`preview_restore_section`). `POST .../worktrees/prune` (**admin** — pode
destruir trabalho de agente não mesclado) remove só os órfãos e devolve o
que foi removido; o banco não é tocado.

## Consequências

**Positivas**
- Um card preso por crash deixa de ser invisível — vira um bloqueio
  acionável, sem inventar um segundo mecanismo de recuperação além do que
  a ADR-0019 já tem.
- Worktree órfão passa a ter um caminho de limpeza que não exige apagar o
  banco inteiro (`reset.sh` continua existindo para o caso extremo).
- Zero regressão: nenhuma orquestração que nunca crashar aciona qualquer um
  dos dois caminhos.

**Negativas / riscos aceitos**
- **O sinal de card órfão é um timeout, não uma certeza** — em teoria um
  agente poderia estar preso mas ainda vivo além do timeout configurado
  (rede lenta, processo suspenso); o bloqueio aparece, mas a ação
  (`route_card`) é do operador decidir, não automática.
- **`_branches_ativas` considera qualquer card não-terminal "ativo"**, mesmo
  que ele nunca tenha de fato rodado (branch vazia) — não gera falso órfão
  (branch vazia não casa com nenhum worktree), só é mais conservador do que
  precisaria em teoria.

## Escopo cortado

Nenhum — Parte 3 do `plano7.md` (`§9. Escopo: o que cortar se apertar`
listava prune e card órfão como os dois itens cortáveis "se apertar") entrou
inteira porque o tempo do incremento permitiu; Partes 1/2 (custo real e
orçamento) estão na [ADR-0026](ADR-0026-custo-real-e-orcamento.md).
