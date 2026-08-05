# ADR-0018 — Kanban fiel: colunas restantes e ativação de dependencies/blocked_by

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-07-30
- **Relaciona-se com:** [ADR-0002](ADR-0002-kanban-as-execution-plane.md) (Kanban
  como plano de execução, não só visual), [ADR-0009](ADR-0009-entrega-de-codigo-governada.md)
  (entrega governada), [ADR-0017](ADR-0017-revisao-independente-de-codigo.md) (precedente
  de coluna nova sem migration), [`fluxo.md`](../../fluxo.md) §8/§10 (requisito de
  origem)

## Contexto

`plano2.md` §10 lista "Kanban fiel" como próximo incremento (`fluxo.md` §8/§10/§23),
mas sem plano detalhado como os incrementos A/B tiveram. Pesquisando o código, o
escopo real tinha quatro partes de tamanho bem diferente — colunas restantes,
`dependencies`/`blocked_by` (campos mortos), auditoria de movimentação
(motivo/resultado/evidência em `CardEvent`) e "ficha de encerramento" (§23) — juntas do
tamanho de um incremento inteiro. Ficou combinado quebrar em duas entregas; esta ADR
cobre só a primeira: **colunas + dependencies/blocked_by**. Auditoria de movimentação e
ficha de encerramento ficam para uma entrega seguinte.

Dois achados concretos motivaram o desenho:

1. As 13 colunas existentes não cobriam `Deploying`/`Validating`/`Cancelled`, que o
   §8 do `fluxo.md` lista.
2. `KanbanCard.dependencies`/`blocked_by` já existiam no modelo e já eram persistidos
   (`_CARD_RELS` em `db/repository.py`) — mas nunca eram populados nem lidos em
   nenhuma lógica de negócio. `docs/api.md` chegou a **afirmar incorretamente** que
   `POST /cards/{id}/run` respeitava `depends_on` — documentação morta descrevendo um
   comportamento que nunca existiu.

## Opções consideradas

**Para as colunas:**
1. **Migration nova para o `status` do card.** Rejeitada: `status` já é `String` puro
   no ORM (mesmo precedente do `NeedsFix` na ADR-0017) — nenhuma coluna nova precisa
   existir para o Kanban aceitar um valor de enum a mais.
2. **Construir o gatilho automático de implantação/validação junto.** Rejeitada:
   é o próprio Incremento F ("gate governado + comando por ambiente"), que ainda não
   foi desenhado. Misturar aumentaria a superfície sem fechar nada — a coluna existir
   e ser selecionável via `POST /cards/{id}/move` (que já aceita qualquer `ColumnKey`)
   já satisfaz "Kanban fiel" nesta fase.

**Para `dependencies`/`blocked_by`:**
3. **Bloquear o card já no nascimento** (status inicial `Blocked` em vez de `Ready`
   quando há dependência). Rejeitada: o `run_plan` (execução multiagente automática)
   já lê `card.status == Ready` a cada onda para decidir o que executar — nasce
   `Blocked` quebraria esse mecanismo, que já ordena corretamente por `depends_on` a
   nível de agente. Cards continuam nascendo `Ready`.
4. **Hook de desbloqueio automático em `merge_pr`/`decide_approval`** (varrer cards
   dependentes toda vez que um card chega a `Done` e promovê-los). Rejeitada nesta
   entrega: a granularidade não bate — `run_plan` libera a próxima onda assim que a
   dependência **termina a execução** (`Testing`/`WaitingHuman`/etc.), não quando ela
   chega a `Done` (que só acontece depois de PR+CI+revisão+merge, um fluxo
   completamente separado). Um hook em `merge_pr` ficaria sistematicamente atrasado
   demais para ajudar o `run_plan`, e o `run_plan` já não precisa dele. Escolhida a
   opção 5.
5. **Verificação só no caminho manual (`run_card`), sem tocar `run_plan`.** Escolhida.

## Decisão

**(1) Sem migration.** `ColumnKey.DEPLOYING`, `VALIDATING`, `CANCELLED` são só valores
de enum a mais sobre uma coluna `String` já existente; `dependencies`/`blocked_by` já
tinham persistência pronta, só nunca eram escritos.

**(2) Ordem das 16 colunas** (`_DEFAULT_COLUMNS`, `board_service.py`): `Backlog, Ready,
Planning, InProgress, WaitingAgent, WaitingHuman, Review, NeedsFix, Testing, Deploying,
Validating, Blocked, Failed, Done, Cancelled, Archived`. `Deploying`/`Validating` entre
`Testing` e `Blocked` (o `fluxo.md` as coloca antes de "Concluído"); `Cancelled` logo
depois de `Done` (`Archived` é housekeeping próprio do ASO, sem equivalente no
`fluxo.md`).

**(3) `Deploying`/`Validating` sem endpoint novo.** Só entram em `ColumnKey` +
`_DEFAULT_COLUMNS`; `POST /cards/{id}/move` genérico já aceita qualquer coluna válida.
Nenhuma automação decide quando um card entra nelas — é trabalho do Incremento F.

**(4) `cancel_card`, espelhando `block_card`/`unblock_card`.** Novo
`OrchestrationService.cancel_card` e `POST /v1/orchestrations/{id}/cards/{card_id}/cancel`
(`body: {reason}`), reaproveitando o mesmo `BlockBody` — move o card para `Cancelled`
com o motivo. Distinto do kill-switch `POST .../cancel` (orquestração inteira).

**(5) `dependencies` = grafo estático populado na criação.** No mesmo laço de
`create_orchestration` que já cria um `KanbanCard` por agente planejado
(`plan.agents`), uma segunda passada mapeia nome-de-agente → `card.id` (os IDs só
existem depois que todos os cards da onda nasceram) e popula
`card.dependencies = [id_por_agente[dep] for dep in planned.depends_on if dep in
id_por_agente]`. Dependência apontando para um agente fora do plano é descartada
silenciosamente — ele não participou desta estratégia. `populate_from_plan`
(planejamento via LLM) fica de fora: `BacklogItem` não tem `depends_on` no schema
hoje, e adicioná-lo é escopo novo, não "ativar campo morto" — limitação aceita.

**(6) `blocked_by` = subconjunto vivo, recomputado sob demanda.** Nenhum evento em
segundo plano mantém `blocked_by` atualizado. `run_card` ganha um guard logo após o
guard existente de agente/card inválido: calcula `_pending_dependencies` (dependências
cujo card ainda não é `Done`); se houver, popula `card.blocked_by`, move o card para
`Blocked` com `block_reason` citando os títulos, e recusa (`ValueError` → `409`, já
mapeado no endpoint). Uma nova tentativa de `run_card` — manual, ou via `/retry` —
recomputa do zero: se a dependência já resolveu, `blocked_by` fica vazio e a execução
segue normalmente, sem exigir um `/unblock` manual antes. Isto vale **só** para o
caminho manual — `run_plan` nunca chama `run_card` diretamente (usa
`_execute_isolated`), então não é afetado por este guard e continua ordenando por
`PlannedAgent.depends_on` como sempre fez.

**(7) UI.** As 3 colunas novas entram nos três arrays hardcoded de colunas
(`macro.html`, `index.html`, `detalhe.html`) — nenhum CSS depende de contagem fixa
(`display:flex`, não grid). `blocked_by` não-vazio aparece como uma linha informativa
junto do `block_reason` já existente no card, nos dois lugares que já mostram
`block_reason`.

## Consequências

**Positivas**
- `docs/api.md` deixa de mentir sobre `depends_on` — a frase que já existia lá agora é
  verdade.
- `dependencies`/`blocked_by` deixam de ser campos mortos sem quebrar o `run_plan`, que
  já funcionava corretamente e não precisou de nenhuma mudança.
- Cancelamento de card individual, distinto do kill-switch de orquestração, fecha uma
  lacuna real (só existia a nível de orquestração antes).
- Zero migration — risco de regressão em Postgres/produção é mínimo.

**Negativas / riscos aceitos**
- `blocked_by` só reflete a realidade depois de uma tentativa de `run_card` — um card
  com dependência pendente que ninguém tentou rodar ainda mostra `blocked_by` vazio
  (campo "preguiçoso", não observador ativo). Aceito: manter simples nesta entrega;
  um observador ativo (hook em toda transição para `Done`) fica para se algum dia isso
  incomodar na prática.
- `populate_from_plan` (planejamento via LLM) não popula `dependencies` — cards vindos
  desse caminho nunca ficam bloqueados por dependência, mesmo que a demanda descreva
  uma sequência. Aceito como limitação documentada, não escopo desta entrega.
- `Deploying`/`Validating` são colunas "decorativas" até o Incremento F desenhar o
  gate de implantação — hoje só servem para o operador mover manualmente.
- Descobrimos (e corrigimos) que `aso run` (CLI) e um teste de integração
  (`test_governance_endpoints.py`) tinham loops manuais de `run_card` por card, sem
  respeitar ordem — funcionavam só porque `dependencies` era campo morto. Ambos
  passaram a usar `run_plan`, que já existia para isto. Não é regressão desta ADR: era
  um comportamento sempre implicitamente errado, só nunca exercitado.

## Emenda (2026-07-30, ADR-0019)

A auditoria de movimentação (§8 do `fluxo.md`), adiada explicitamente nesta ADR
("Deliberadamente adiado" no plano de origem), saiu na
[ADR-0019](ADR-0019-roteamento-de-falha.md) §2 — por sinergia com o §13 (registrar
causa/próxima ação a cada falha): `CardEvent` ganhou `reason`/`result`/`evidence`/
`next_action`, preenchidos por `move_card`/`apply_event` a cada movimentação, não só
quando o destino é `Blocked`. A **ficha de encerramento do card (§23)** continua
pendente — é um bloco coeso e independente, ainda sem incremento definido.

## Emenda (2026-07-31, ADR-0021)

As duas limitações aceitas acima foram resolvidas na
[ADR-0021](ADR-0021-especificacao-e-revisao-documental.md) (D2, §4.6/§4.7):

- **`populate_from_plan` agora popula `dependencies`**: `BacklogItem.depends_on`
  (títulos de irmãos do backlog) resolvido título→id numa segunda passada, mesmo
  padrão de `PlannedAgent.depends_on`. `full-pipeline` — o modo default — passa por
  este caminho; sem a correção, quase nenhum card de produção nascia com
  dependência.
- **`blocked_by` deixou de ser só preguiçoso**: `BoardService._refresh_dependents`
  observa toda transição para `Done` e recalcula `blocked_by` dos dependentes,
  liberando automaticamente (`Blocked` → `Ready`) um card que estava bloqueado
  **especificamente** por dependência quando ela resolve. Deliberadamente
  conservador: não mexe em card bloqueado por outro motivo, e
  `_pending_dependencies` continua sendo a checagem autoritativa antes de
  qualquer execução — o observador é conveniência, não a fonte de verdade.

A **ficha de encerramento do card (§23)** também saiu na ADR-0021 §4.5.

## Emenda (2026-07-31, ADR-0023)

O "Incremento F" citado três vezes acima (Decisão §3, Opções consideradas,
Consequências negativas) fechou na
[ADR-0023](ADR-0023-implantacao-governada.md): implantação governada com
comando configurável (§18-22 do fluxo.md), exatamente a fórmula "gate
governado + comando por ambiente" já antecipada aqui. Uma ressalva
deliberada: **as colunas `Deploying`/`Validating` continuam sem automação de
transição** — a governança de implantação foi modelada no nível da
ORQUESTRAÇÃO (como discovery/spec), não por card, então o gatilho automático
de coluna que este ADR previa segue como trabalho futuro, agora sem um "card
certo" óbvio para mover.

## Emenda (2026-07-31, ADR-0025)

`KanbanCard` ganha `parent_id` (§7 do fluxo.md — hierarquia épico → história
→ subtarefa), pendência nomeada três vezes desde o `plano4.md`. `move_card`
ganha uma segunda regra de dependência, além de `blocked_by`: um card com
filho ainda aberto (fora de `Done`/`Cancelled`) não pode chegar a `Done`, e
cancelar um card cancela os filhos ainda abertos em cascata — mesmo espírito
de "dependente de card cancelado nunca fica órfão em silêncio" já registrado
acima para `dependencies`. Detalhe completo em
[ADR-0025](ADR-0025-qa-hierarquia-aprendizado.md).
