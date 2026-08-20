# ADR-0040 — Estrutura da demanda em árvore (Tela 10)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-07
- **Relaciona-se com:** [ADR-0025](ADR-0025-checklist-de-preparacao-e-qa-manual.md)
  (`KanbanCard.parent_id`, `hierarchy.py` original), [ADR-0034](ADR-0034-design-system-wireframe.md)
  (componente `.tree`, criado no FID-07 sem nenhuma tela usá-lo até agora),
  [ADR-0039](ADR-0039-cadastro-de-demanda-completo.md) (página satélite
  `/ui/demanda-nova`, mesmo padrão desta), [`wiframe-fluxo.md`](../../wiframe-fluxo.md)
  §12 (requisito de origem)

## Contexto

O `wiframe-fluxo.md` §12 pede uma árvore navegável, expansível, com criação
de item em qualquer nível e navegação do nó para o detalhe do card. A
descrição do card FID-13 fala em 5 níveis (Projeto → Épico → História →
Card → Subtarefa), mas a investigação prévia encontrou duas lacunas reais
antes de qualquer código:

- **O próprio wireframe (§12.1/§12.2) só desenha 3 níveis** (Épico → História
  → Card) — "Subtarefa" não aparece em nenhum texto nem diagrama da seção 12,
  só na descrição do card no board.
- **`hierarchy.py` (ADR-0025) já existe, mas só tem primitivas de nível
  único** (`profundidade`, `filhos`, `fecha_ciclo`) — nenhuma função monta a
  árvore inteira. `PROFUNDIDADE_MAXIMA = 3` hoje trava exatamente em `Epic →
  Feature → Task` — o mesmo teto que barra logicamente uma "Subtarefa" (um
  4º nível).
- **"História" e "Subtarefa" não são tipos de `CardType`** — o mais próximo
  de "História" é `FEATURE` (já usado com esse papel em `hierarchy.py`,
  `qa.py`); "Subtarefa" não tem representação nenhuma.
- **"Projeto" não bate com nenhuma entidade que agrupe cards** —
  `Project` agrupa orquestrações, não cards; um board pertence a UMA
  orquestração. O próprio wireframe §12.2 nem desenha esse nó.
- **Nenhum endpoint HTTP expõe a hierarquia ou cria cards hoje.**

Este ADR documenta as decisões tomadas para essas lacunas — a primeira
(subir `PROFUNDIDADE_MAXIMA`) foi confirmada explicitamente com o usuário,
entre duas opções oferecidas.

## Decisão

**(1) `PROFUNDIDADE_MAXIMA` sobe de 3 para 4** (`hierarchy.py`). "Subtarefa"
não é um `CardType` novo — é o mesmo `TASK`, com `parent_id` apontando para
outro `TASK`. A árvore real de `parent_id` passa a comportar `Epic → Feature
→ Task → Task` (4 níveis navegáveis), validada pela mesma checagem que já
existia em `BoardService.add_card` (existência do pai, ausência de ciclo,
profundidade) — só o teto mudou. Testado explicitamente contra o Postgres/
SQLite real (via `pytest`) e contra a API real (dev server): nível 4 aceito,
nível 5 recusado com `409` e mensagem explicando o motivo.

**(2) "Projeto" é rótulo de contexto estático, não nó expansível.** A árvore
é da **demanda** (uma orquestração específica — "Estrutura da demanda",
singular, tanto no título da tela quanto no `§12.1`), não do projeto
inteiro. A página mostra o nome/resumo da demanda no cabeçalho (via `GET
/v1/orchestrations/{id}`), mas a árvore em si começa nas raízes reais dos
cards daquela orquestração (tipicamente `Epic`, mas qualquer card sem
`parent_id` aparece como raiz — inclusive os cards automáticos do plano de
execução, que hoje nascem sem hierarquia).

**(3) "História" usa `CardType.FEATURE`** — reaproveita o valor que
`hierarchy.py`/`qa.py` já tratam como o nível intermediário, só com o
rótulo "História" na UI (`type: "Feature"` no payload, exibido como
"História" no formulário de criação).

**(4) `montar_arvore(cards)` — função pura nova em `hierarchy.py`.** Recebe
o mesmo mapa `{id: KanbanCard}` das demais funções do módulo; devolve uma
lista de dicts aninhados (`id`, `title`, `type`, `status`, `assignee`,
`filhos`) — não `KanbanCard` aninhado, para o endpoint HTTP servir a
resposta sem remontar nada. Recursiva sobre `filhos()`, que já existia; a
mesma garantia de `PROFUNDIDADE_MAXIMA` que impede ciclo/árvore infinita em
`add_card` já limita a recursão aqui (nenhum limite extra necessário).

**(5) Dois endpoints novos**: `GET /v1/orchestrations/{id}/cards/tree`
(árvore montada) e `POST /v1/orchestrations/{id}/cards` (cria item em
qualquer nível — `título`, `tipo`, `parent_id` opcional, `descrição`
opcional). O segundo reaproveita `BoardService.add_card` integralmente —
`parent_id` inexistente, ciclo ou profundidade excedida devolvem `409`
com a mesma mensagem que a validação interna já produz, sem duplicar regra
nenhuma no handler HTTP.

**(6) Navegação do nó volta para `/ui/detalhe?id=<orquestração>`, sem
destacar o card específico.** Não existe hoje nenhum mecanismo de deep-link
a um card dentro de `detalhe.html` (sem hash, sem query param de card, sem
`id="card-..."` nos elementos) — introduzir um novo protocolo de
âncora/highlight só para este card seria escopo além do que a Tela 10 pede
(ela mesma não especifica esse comportamento, só o card do board). Documentado
como limitação honesta, não escondida.

**(7) Estado de expansão em `localStorage`, por orquestração.** Chave
`aso_tree_expanded_<orchestration_id>` guarda os ids dos nós abertos — sem
histórico de navegação nem estado no servidor, já que "estado de expansão
preservado" é sobre reabrir a mesma tela depois, não sobre compartilhar/
persistir entre usuários.

**(8) `demandas.html` (Tela 02, FID-11): "Visualizar cards" agora aponta
para `/ui/demanda-estrutura?id=`, não mais para `/ui/detalhe?id=`.**
Pequena correção retroativa: a Tela 10 é o destino real e melhor para essa
ação (FID-11 tinha apontado para o detalhe legado só porque a estrutura
ainda não existia). `/ui/detalhe` continua acessível por "Abrir"/
"Histórico"/"Documentos" na mesma linha.

**(9) Página satélite nova `/ui/demanda-estrutura`**, mesmo padrão de
`/ui/demanda-nova` (FID-12/ADR-0039): header+sidebar (seção "demandas"
ativa), fora da lista fixa de 16 seções, recebe `?id=<orchestration_id>`.

## Consequências

**Positivas**
- O componente `.tree` (criado no FID-07, ADR-0034, sem uso até agora) tem
  finalmente uma tela consumindo-o.
- "Criar item em qualquer nível" funciona de ponta a ponta — testado contra
  a API real (criação de Épico → História → Card → Subtarefa em sequência,
  cada nível confirmado na árvore montada pelo backend).
- Nenhuma orquestração/card existente muda de comportamento — `parent_id`
  continua opcional, cards sem hierarquia aparecem como raízes soltas.

**Negativas / riscos aceitos**
- "Subtarefa" como 4º nível é uma interpretação nossa (Task filho de Task),
  não uma citação literal do wireframe — documentado aqui para não ser
  confundido com um requisito textual da fonte.
- Sem deep-link ao card específico no detalhe — o clique no nó leva para a
  orquestração inteira, não para o card em destaque.
- `montar_arvore` reconstrói a árvore inteira a cada chamada (sem cache) —
  aceitável no volume "dev-scale" do projeto, mesmo raciocínio já usado em
  `header_summary`/`search` (ADR-0035).
