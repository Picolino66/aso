# ADR-0030 — Checklist de preparação e tarefa vinculada por dependência

- **Status:** ACCEPTED
- **Fase:** F5 (preparação para implementação)
- **Data:** 2026-08-06
- **Relaciona-se com:** [ADR-0018](ADR-0018-kanban-fiel-colunas-e-dependencias.md) (bloqueio por
  dependência, `_pending_dependencies`/`blocked_by` — esta ADR estende o mecanismo, não o
  substitui), [ADR-0019](ADR-0019-roteamento-de-falha.md) (padrão de política pura),
  [ADR-0025](ADR-0025-qa-hierarquia-aprendizado.md) (`qa_checks`, precedente direto de "lista de
  itens versionada no card"), [`fluxo.md`](../../fluxo.md) §10, [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §16

## Contexto

`fluxo.md` §10 lista 8 itens que o agente cumpre antes de alterar código
(especificação lida, critérios de aceite analisados, código afetado analisado,
dependências verificadas, testes existentes identificados, branch criada, plano
de execução registrado, card desbloqueado) e fecha com: *"Se houver uma
dependência pendente, o card é movido para 'Bloqueado'. O orquestrador identifica
a dependência e cria uma tarefa adicional para resolvê-la."*

A investigação confirmou: o bloqueio por dependência já existe desde a ADR-0018
(`run_card` → `_pending_dependencies` → `Blocked` com os títulos citados) — mas
os 8 itens do checklist não tinham forma alguma no código (nem campo, nem
validação, nem UI), e nenhuma tarefa vinculada era criada automaticamente.
`docs/plano-fidelidade-fluxo.md:76-77` já registrava isso como "10% coberto —
os 8 itens são executados implicitamente; não há registro auditável".

## Decisão

### 1. O que "concluído" significa em cada item — limite deliberado

`control/preparation.py` marca os 8 itens **automaticamente**, nunca por escrita
manual (não existe `POST` para o checklist, só `GET`) — um checklist editável à
mão mentiria sobre o que de fato foi verificado, o oposto do que o §10 pede.
Cada marcação representa um **fato estrutural do runtime**, nunca uma confirmação
de julgamento do agente:

| Item | Marcado quando... | Fato que representa |
|---|---|---|
| Especificação lida | `_build_task` monta o prompt | `card_description` foi incluída no que o agente recebeu |
| Critérios de aceite analisados | idem | `acceptance_criteria` foi incluída |
| Código afetado analisado | idem | o agente ganhou acesso de escrita ao worktree/repositório |
| Testes existentes identificados | idem | `validation_command`/bateria foi incluída no prompt |
| Plano de execução registrado | idem | naming (branch/commit) foi resolvido antes da execução |
| Dependências verificadas | `run_card` roda o guard `_pending_dependencies` | o guard executou (bloqueando ou não) |
| Card desbloqueado | `run_card` passa do guard sem pendência | nenhuma dependência impede a execução |
| Branch criada | `_apply_execution` grava `card.branch` a partir do artifact | a branch existe de fato, com nome |

Os cinco primeiros **nunca provam** que o agente leu/aplicou nada — só que o
runtime entregou a informação. Isto é intencional e documentado no docstring do
módulo: inventar uma confirmação de leitura que nenhum runtime determinístico
pode verificar seria pior que não ter o item.

### 2. Onde a marcação entra — compartilhado entre os três caminhos de execução

`_build_task(b, card, agent, *, effort=None)` é chamado por **`race_card`**
(corrida de candidatos, §26A.6), **`run_card`** (execução manual) e **`run_plan`**
(autopilot, execução multiagente automática) — os três caminhos de execução do
runtime. Marcar os 5 itens de "entrega de contexto" **dentro de `_build_task`**
cobre os três de uma vez, sem duplicar a lógica e sem exigir uma chamada extra
em cada caminho.

"Dependências verificadas"/"Card desbloqueado" e a tarefa vinculada ficam **só**
no guard de `run_card` — o único lugar do runtime onde bloqueio por dependência
acontece hoje (`race_card`/`run_plan` deliberadamente não passam por esse guard
desde a ADR-0018: cards nascem `Ready`, e `run_plan` já ordena as próprias ondas
por `depends_on`). Não reabre essa decisão.

"Branch criada" fica em `_apply_execution` (compartilhado por `run_card` e
`run_plan`, não por `race_card`, que não chama `_apply_execution`) — o ponto
exato em que `card.branch` é gravado a partir do artifact real da execução.

### 3. Estado, não log — `marcar_item` faz upsert, não acumula

Diferente de `card.failures`/`qa_checks` (ring de eventos — cada tentativa é um
registro novo), o checklist de preparação é **estado**: no máximo 8 entradas, uma
por item do vocabulário fechado do §10. `marcar_item` substitui a entrada
existente do mesmo item em vez de acrescentar — uma nova tentativa de `run_card`
depois de uma falha não duplica "Dependências verificadas" cinco vezes, só
atualiza o timestamp da marcação mais recente.

### 4. Tarefa vinculada — por que não é redundante com a dependência em si

Como `card.dependencies` já são IDs de outros cards do mesmo board, "criar mais
uma tarefa para resolver a dependência" pareceria redundante à primeira vista — a
dependência já é uma tarefa. A leitura adotada: a tarefa vinculada não substitui
a dependência, é um **ponto de triagem do card bloqueado**, distinto e mais leve
que a dependência (que pode ser grande, já em andamento, sem foco em
"desbloquear especificamente este card"). `_criar_tarefa_vinculada` cria um
`KanbanCard(type=Task, status=Backlog)` citando os títulos pendentes, e
`card.dependency_task_id` guarda o ponteiro — **idempotente**: só é criada na
primeira vez que o card bloqueia (`dependency_task_id is None`); tentativas
repetidas do mesmo bloqueio reaproveitam a mesma tarefa. Quando a dependência
resolve e o card desbloqueia, o ponteiro é limpo (`dependency_task_id = None`) —
a tarefa em si permanece no board, sob responsabilidade do operador fechá-la ou
não; o runtime não a fecha automaticamente (mesma disciplina do card de
incidente criado por `rollback_deploy`, ADR-0023: o runtime cria, o operador
decide o destino).

### 5. Persistência — mesmo padrão de `failures`/`qa_checks`, sem tabela nova

`KanbanCard.preparation_checklist: list[dict[str, Any]] = []` e
`dependency_task_id: str | None = None` — dicts soltos (não os tipos Pydantic de
`control/preparation.py`), pelo mesmo motivo de `failures`/`qa_checks`: `kanban`
não importa `control`. Migration única (`4d45e012f59d`, `down_revision=
ae6259d3dc8b`) adiciona as duas colunas a `kanban_cards`, mesmo padrão de
`f65a28d4e213` (`qa_checks`). Nenhuma tabela nova, nenhuma normalização em
`card_links` (que é só para listas de string simples).

### 6. Encerramento e API

`_build_card_closure` (§23, preenchida em `merge_pr`) ganha a chave
`checklist_preparacao: card.preparation_checklist` — satisfaz "evidência do
checklist aparece no encerramento do card" sem inventar um campo novo na ficha.

`GET /v1/orchestrations/{id}/cards/{card_id}/checklist` (viewer) — só leitura,
espelhando `GET .../qa`. Não existe `POST` equivalente: ver §1.

## Consequências

**Positivas**
- Os 8 itens do §10 deixam de ser implícitos — ficam auditáveis por card, com
  autor e timestamp, sem exigir nenhuma chamada extra do operador (o próprio
  fluxo de execução já preenche o checklist).
- A tarefa vinculada dá ao operador um ponto de ação imediato quando um card
  bloqueia, sem exigir que ele investigue `blocked_by` manualmente.
- Zero regressão: nenhum campo novo tem efeito sobre nenhuma validação
  existente — `checklist_completo()` não é chamada por nenhum guard hoje (não
  bloqueia nada); é só evidência.

**Negativas / riscos aceitos**
- Os itens "Especificação lida"/"Critérios de aceite analisados"/"Código afetado
  analisado"/"Testes existentes identificados"/"Plano de execução registrado"
  registram entrega de contexto, não confirmação de leitura — um leitor do
  checklist que não conhecer essa distinção pode superestimar o que ela prova.
  Documentado explicitamente no docstring do módulo e nesta ADR para não deixar
  dúvida.
- "Branch criada" só marca quando a execução produz um artifact `branch` — com
  o executor mock (sem worktree real) o item nunca marca, o que é correto (não
  há branch de fato), mas pode surpreender quem espera o checklist sempre
  completo em ambiente de teste.
- A tarefa vinculada nunca é fechada automaticamente pelo runtime — fica
  acumulando no board até o operador agir. Aceito por ser o mesmo padrão já
  usado para o card de incidente do rollback (ADR-0023).
- Nenhum guard novo bloqueia execução por checklist incompleto — `checklist_
  completo()` existe como função pura, mas não é chamada por `run_card`/gate
  hoje. Se um bloqueio por checklist incompleto for desejado no futuro, é
  extensão aditiva sem quebra de contrato.
