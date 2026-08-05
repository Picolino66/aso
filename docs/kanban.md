# Kanban — ASO Runtime

> Fase F4. O Kanban é o **plano de execução** (ADR-0002), não apenas visual. Board inicial em [`.aso/kanban/board.json`](../.aso/kanban/board.json).

## Colunas (§16.2)

`Backlog → Ready → Planning → In Progress → Waiting Agent → Waiting Human → Review → Needs Fix → Testing → Deploying → Validating → Blocked → Failed → Done → Cancelled → Archived`

`NeedsFix` ("Aguardando correção", [ADR-0017](adrs/ADR-0017-revisao-independente-de-codigo.md))
entra logo após `Review`, na ordem do §8 do `fluxo.md`: um card cai aqui quando a
revisão independente pede alterações obrigatórias — distinto de `Review`, que ainda
não tem veredito.

`Deploying`/`Validating`/`Cancelled` ([ADR-0018](adrs/ADR-0018-kanban-fiel-colunas-e-dependencias.md))
completam a lista de colunas do §8. `Cancelled` tem endpoint próprio,
`POST /cards/{id}/cancel`, espelhando `block`/`unblock`.

`Deploying`/`Validating` continuam selecionáveis só via `POST /cards/{id}/move`
genérico — desde a [ADR-0023](adrs/ADR-0023-implantacao-governada.md) (§18-22 do
fluxo.md, "Incremento F"), a governança de implantação existe e é rica
(`GET/PUT .../deploy/config`, `POST .../deploy/run|validate|approve|rollback`,
critério `deploy_aprovado` no gate de F6), mas opera no nível da ORQUESTRAÇÃO, não
do card — não há um "card certo" para mover automaticamente sem inventar um vínculo
artificial. A automação de transição de COLUNA continua manual; ver
[`docs/operations.md`](operations.md) para o fluxo completo.

### Dependências entre cards (§10)

`KanbanCard.dependencies` (IDs dos cards que este precisa) é populado na criação a
partir de `PlannedAgent.depends_on` do plano multiagente — ex.: numa estratégia
paralela, o `ReviewAgent` sempre depende dos workers de domínio. Desde a
[ADR-0021](adrs/ADR-0021-especificacao-e-revisao-documental.md) (§4.6), o mesmo vale
para os dois outros caminhos de criação de cards: `populate_from_plan`
(`BacklogItem.depends_on`, planejamento via LLM — o caminho que `full-pipeline`, o
modo default, usa de verdade) e os `itens_de_trabalho` de uma especificação aprovada
(`SpecWorkItem.depende_de`). Em todos, a dependência referencia o **título** de um
card irmão e é resolvida para id numa segunda passada — título desconhecido é
descartado, não quebra a criação.

`blocked_by` é a fatia de `dependencies` ainda não `Done`. Recomputado quando
alguém tenta rodar o card manualmente (`POST /cards/{id}/run` recusa com `409` e
move para `Blocked` havendo pendência) **e**, desde a ADR-0021 (§4.7), também de
forma ativa: toda vez que um card chega a `Done`, `BoardService._refresh_dependents`
recalcula `blocked_by` de quem depende dele e libera automaticamente
(`Blocked` → `Ready`) quem estava bloqueado especificamente por essa dependência.
Um card com dependência pendente que ninguém tentou rodar deixa de aparecer
falsamente como pronto. Isto vale só para o caminho manual/observador — o `run_plan`
(execução multiagente automática) já ordena por `depends_on` nas suas próprias
ondas e não passa por nenhum dos dois guards.

Desde a [ADR-0022](adrs/ADR-0022-bateria-de-validacoes-e-effort-automatico.md), o
mesmo observador também reage a `Cancelled`/`Archived` — mas **não** libera o
dependente: bloqueia com motivo explícito
(`"dependência(s) cancelada(s)/arquivada(s): <título>"`), porque a dependência não
foi satisfeita, foi abandonada. Liberar em silêncio deixaria o card rodar sem o que
ele precisava.

### Hierarquia épico → história → subtarefa (§7)

`KanbanCard.parent_id` ([ADR-0025](adrs/ADR-0025-qa-hierarquia-aprendizado.md))
— nulo (todo card anterior a esta ADR) continua válido, a hierarquia é
opcional. Regras aplicadas por `BoardService` (`kanban/hierarchy.py`, funções
puras): **profundidade máxima 3** (Epic → Feature → Task); **ciclo é erro**;
**um card com filho ainda aberto (fora de `Done`/`Cancelled`) não chega a
`Done`**; **cancelar o pai cancela os filhos** ainda abertos, em cascata —
filho já `Done` fica como está. Produzida por `SpecWorkItem.itens_filhos`
(um nível, resolvido pelo título do pai na mesma segunda passada que resolve
`depende_de`) e por `BacklogItem.type` (sem árvore, o caminho de plano do LLM
permanece flat).

### QA manual (§16/§17)

`KanbanCard.qa_checks` ([ADR-0025](adrs/ADR-0025-qa-hierarquia-aprendizado.md))
— ring de 10 verificações manuais (`GET`/`POST .../cards/{id}/qa`). Exigida
(`control/qa.py::exige_qa_manual`) quando o domínio da ficha inclui
`frontend`, a complexidade é `complexa`/`estrategica`, ou o card é
`Epic`/`Feature` — fora disso, opcional. Reprovação (`POST
.../qa/{i}/fail`) cria um card `Bug` vinculado por `dependencies` (e por
`parent_id` quando a profundidade permitir) e registra a falha no roteamento
existente (`control/failure.py`, diagnóstico `falha_de_qa`, sem taxonomia
nova) — o card original volta para `NeedsFix` ou `Failed` conforme a
política já decide para qualquer outra falha.

### Ficha de encerramento (§23)

`KanbanCard.closure` ([ADR-0021](adrs/ADR-0021-especificacao-e-revisao-documental.md),
§4.5) é preenchida em `merge_pr` — o ponto em que o card chega a `Done`: resumo,
executor, revisor, branch, id da PR, rodadas de revisão, versões correntes de
discovery/spec (quando existirem) e riscos residuais (ações do veredito de
severidade `sugestao`). Vazio até o merge. Só registra o que o runtime tem à mão —
campos do §23 sem dado disponível (data de implantação, commits individuais) não
aparecem inventados. Exposta em `GET /cards/{id}/closure` e no próprio `GET` do
card.

## Swimlanes (§16.3)

Por fase (F1–F7), por agente, por épico, por prioridade, por tipo de trabalho, por release. Board MVP-1 usa swimlane por **épico**.

## Tipos de card (§16.4)

`Epic, Feature, Task, Bug, TechDebt, ADRTask, Research, Review, Test, Documentation, Deploy, Incident, Improvement`

## Automação por eventos (§16.7)

| Evento | Transição |
|---|---|
| Agent started | → In Progress |
| Agent needs input | → Waiting Human |
| PR opened | → Review |
| CI failed | → Needs Fix ([ADR-0019](adrs/ADR-0019-roteamento-de-falha.md) — corrigível, não beco sem saída) |
| Review requested changes | → Needs Fix (ADR-0017) |
| Tests passed | → Testing / Done |
| Quality gate passed | → Done |
| Quality gate failed | → Blocked |

`Failed` não é mais alcançado por qualquer falha de execução: desde a ADR-0019, é
reservado ao que o **roteamento de falha** (§13 do `fluxo.md`) decidiu escalar para
humano depois de esgotar as tentativas automáticas — ver
[`docs/operations.md`](operations.md#roteamento-de-falha).

## Regras (§16.6)

Todo trabalho executável vira card com fase; card técnico tem critério de aceite; card de agente registra agente; card que altera arquitetura vincula ADR; card que altera API vincula contrato; card de código vincula branch/worktree/PR; card bloqueado registra motivo; card finalizado tem evidência.
