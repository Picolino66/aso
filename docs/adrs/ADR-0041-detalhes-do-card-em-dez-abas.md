# ADR-0041 — Detalhes do card em dez abas (Tela 12)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-07
- **Relaciona-se com:** [ADR-0040](ADR-0040-estrutura-da-demanda-em-arvore.md)
  (página satélite `/ui/demanda-estrutura`, mesmo padrão desta; fecha a lacuna
  de deep-link que a ADR-0040 documentou como limitação honesta),
  [ADR-0019](ADR-0019-roteamento-de-falha.md)/[ADR-0031](ADR-0031-limite-de-tentativas.md)
  (rings `failures`/`tentativas`, truncados), [ADR-0033](ADR-0033-comentario-de-revisao-ancorado.md)
  (`ReviewComment.card_id`), [ADR-0025](ADR-0025-qa-hierarquia-aprendizado.md)
  (`CardEvent`, `BoardService.card_events`, hierarquia), [`wiframe-fluxo.md`](../../wiframe-fluxo.md)
  §14 (requisito de origem)

## Contexto

O `wiframe-fluxo.md` §14 lista os campos obrigatórios de um card (§14.1) e os
nomes das 10 abas (§14.2) **em duas listas separadas, sem cruzamento** — o
texto não diz qual campo pertence a qual aba. A investigação prévia encontrou
mais lacunas reais antes de qualquer código:

- **Objetivo, Contexto, Riscos, Evidências esperadas e Complexidade só
  existem no `DemandBrief` da ORQUESTRAÇÃO** (`GET .../brief`), não por card —
  seriam idênticos para todos os cards da mesma demanda se usados como estão.
- **Modelo selecionado e Nível de effort não são campos estáticos do card** —
  só existem por tentativa, dentro do ring `KanbanCard.tentativas`
  (`TentativaRegistro.executor`/`.effort`).
- **Não existia `GET .../cards/{card_id}`** (leitura de um card só) nem
  qualquer endpoint que exponha `BoardService.card_events` — o log
  append-only de movimentações (§8 do fluxo.md) já é coletado e persistido
  integralmente, mas nunca foi servido por HTTP.
- **"Histórico de execução nunca sobrescrito" (critério de aceite) colide
  com os rings truncados**: `failures` (5), `tentativas` (10), `qa_checks`
  (10) descartam o item mais antigo por design (ADR-0019/ADR-0031).
- **A premissa "hoje o card abre num modal simples" (descrição do card no
  board) não corresponde ao código** — não existe modal nenhum hoje; o que
  existe é renderização inline em `detalhe.html` (`cardNode()`), sem clique.
- `PullRequest.card_id` e `ReviewComment.card_id` já existem, mas nenhum
  endpoint filtra por eles — `list_pulls`/`list_review_comments` devolvem
  tudo da orquestração/PR.

Duas decisões foram confirmadas explicitamente com o usuário entre opções
oferecidas (ambas seguiram a recomendação).

## Decisão

**(1) O mapeamento campo → aba é uma decisão de design deste ADR, não uma
citação do wireframe.** Adotado:
- **Resumo**: identificação (código/tipo/status/prioridade), objetivo/
  contexto/riscos/complexidade (herdados do `DemandBrief`, rotulados
  explicitamente "herdado da demanda" — nunca apresentados como dado do
  card), descrição, agente/executor.
- **Plano**: critérios de aceite, checklist de preparação, ações de correção.
- **Implementação**: worktree, branch, motivo de bloqueio, PRs vinculadas.
- **Arquivos**: arquivos/módulos, requisitos/ADRs/contratos vinculados.
- **Testes**: `qa_checks` (ring de 10, cenário/resultado/evidências).
- **Review**: PRs da orquestração filtradas client-side por `card_id`, com
  os comentários de cada uma (`ReviewComment`, já tem `card_id`, mas sem
  filtro server-side — volume por card é pequeno, filtro no cliente é
  suficiente no volume dev-scale do projeto, mesmo raciocínio de
  `header_summary`/`search`, ADR-0035).
- **Evidências**: agrega `evidencias_esperadas` do brief (herdado, rotulado),
  `qa_checks[].evidencias` e `CardEvent.evidence` — não existe hoje um
  agregador único de evidências; a aba compõe a partir de três fontes reais
  em vez de inventar uma entidade `Evidence` que o projeto não tem.
- **Dependências**: `dependencies`/`blocked_by` resolvidos para título (via
  a listagem de cards já carregada), `dependency_task_id` como link.
- **Execuções**: `tentativa_atual`, ring `tentativas` (modelo/effort/
  resultado por tentativa — aqui, não em Resumo, é onde "Modelo selecionado"
  e "Nível de effort" aparecem de fato, já que não são campos estáticos),
  corridas de candidatos (`GET .../candidate-runs?card_id=`, já existia com
  esse filtro) e `failures`.
- **Histórico**: `CardEvent` completo (ver decisão 3) — não os rings.

**(2) Dois endpoints novos, reaproveitando 100% do padrão `_card_op`
existente** (`404` se card/orquestração não existe, `409` em `ValueError`):
- `GET /v1/orchestrations/{id}/cards/{card_id}` — ficha completa do
  `KanbanCard` (`OrchestrationService.get_card`), alimenta sozinha as abas
  Resumo/Plano/Implementação/Arquivos/Testes/Dependências/Execuções sem a
  cliente compor a partir da listagem inteira do board.
- `GET /v1/orchestrations/{id}/cards/{card_id}/events` — devolve
  `BoardService.card_events` filtrado por `card_id`
  (`OrchestrationService.get_card_events`). **Registrado depois de todas as
  rotas literais de um segmento sob `cards/`** (`tree`, `stats`,
  `by-status/{status}`) — Starlette casa rotas por ordem de registro, e
  `GET .../cards/{card_id}` (um segmento, path param) sombrearia qualquer
  rota literal de um segmento registrada DEPOIS dela. Testado explicitamente
  (`test_rotas_literais_de_cards_nao_sao_sombreadas`) para não repetir essa
  classe de bug silenciosamente no futuro.

**(3) "Histórico nunca sobrescrito" é cumprido por `CardEvent`, não pelos
rings.** `BoardService.card_events` já é append-only e já é persistido
integralmente (`CardEventRow`, sem ring) — só faltava o endpoint. A aba
Histórico exibe esse log completo; as abas Execuções/Testes continuam
mostrando os rings truncados (`tentativas`/`qa_checks`), que são o dado
certo para "últimas tentativas", não para "histórico completo".

**(4) Página satélite nova `/ui/card-detalhe?id=<orchestration_id>&card=
<card_id>`**, mesmo padrão de `/ui/demanda-estrutura` (header+sidebar,
`active: 'demandas'`, fora da lista fixa de 16 seções). Componente `.tabs`/
`.tab` reaproveitado — já existia em `components.css` desde o design system
(ADR-0034), criado para o mesmo conceito do wf §6.3 e usado até agora só em
`index.html` (console legado).

**(5) `demanda-estrutura.html`: clique no nó agora leva a
`/ui/card-detalhe?id=...&card=...`, não mais a `/ui/detalhe?id=...`.**
Fecha a lacuna que a ADR-0040 documentou explicitamente como limitação
honesta ("sem deep-link ao card específico") — a Tela 12 é exatamente o
destino que faltava.

## Consequências

**Positivas**
- Primeira tela do projeto a mostrar o log completo de `CardEvent` — dado
  que já existia e já era persistido sem truncar, mas nunca tinha sido
  servido.
- Deep-link nó da árvore → card específico funciona de ponta a ponta,
  fechando uma lacuna documentada há um card.
- Nenhum campo foi fabricado: os 5 campos "herdados da demanda" são
  rotulados como tal na própria UI, nunca apresentados como dado por card.

**Negativas / riscos aceitos**
- Objetivo/Contexto/Riscos/Evidências esperadas/Complexidade são idênticos
  para todos os cards da mesma demanda — decisão explícita do usuário
  (reaproveitar rotulado, não omitir), não uma limitação escondida.
- Filtro de PRs/comentários por card é feito no cliente (busca tudo da
  orquestração e filtra), não no servidor — aceitável no volume dev-scale
  atual; um projeto com centenas de PRs por orquestração exigiria um
  filtro server-side dedicado (mesmo padrão que a Tela 02, FID-11, já
  aplicou para `aprovacao_humana` quando o custo justificou).
- "Testes obrigatórios" (§14.1) não tem campo próprio distinto do que já foi
  executado — a aba Testes mostra `qa_checks` (verificações já registradas),
  não uma lista separada de "testes que deveriam rodar"; não existe essa
  entidade no runtime hoje.
