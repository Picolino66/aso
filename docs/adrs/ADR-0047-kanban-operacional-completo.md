# ADR-0047 — Kanban operacional completo (Tela 11)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-08
- **Relaciona-se com:** [ADR-0002](ADR-0002-kanban-as-execution-plane.md)
  (TASK-04, `specs/kanban.md` — "movimentos inválidos são rejeitados" já era
  critério de aceite original, nunca implementado até aqui), [ADR-0040](ADR-0040-estrutura-da-demanda-em-arvore.md)/[ADR-0046](ADR-0046-documentos-e-revisao-documental.md)
  (páginas satélite `?id=`, mesmo padrão), [`wiframe-fluxo.md`](../../wiframe-fluxo.md)
  §13 (Tela 11) e §35 (máquina de estados)

## Contexto

Numeração conferida: §13 = Tela 11, §35 = máquina de estados (citada como
"wiframe 35" no critério de aceite — seção separada, sem "Tela" própria).

O wireframe pede 14 colunas nomeadas, card resumido com 11 campos, e
movimentação manual respeitando a máquina de estados do §35. Investigação
prévia encontrou:

- **As 14 colunas não mapeiam 1:1 para as 16 `ColumnKey` reais.** "Pronto
  para implantação" não tem `ColumnKey` própria; `WAITING_AGENT` não
  corresponde a nenhuma das 14 (e, adicionalmente, não é usada em lugar
  nenhum da automação real hoje). O diagrama do §35 usa ainda um estado
  `Rollback`, que também não está entre as 14 colunas do §13.1 — 15 estados
  no diagrama, não 14.
- **Não existe HOJE nenhuma validação de transição** — `BoardService.move_card`
  aceita qualquer origem→destino, sem checagem. Mas isso **não é uma lacuna
  nova**: `specs/kanban.md` (TASK-04, ADR-0002) já listava "movimentos
  inválidos (transição não permitida pela máquina) são rejeitados" como
  critério de aceite original, nunca implementado. Este card paga essa
  dívida, não inventa escopo novo.
- **8 dos 11 campos do card resumido não são campos diretos de `KanbanCard`**
  — precisam ser derivados (modelo/effort do último item do ring
  `tentativas`; indicador de aprovação humana cruzando `HumanApproval.card_id`;
  tempo na etapa a partir de `updated_at`, confirmado como o único campo do
  card mutado exclusivamente por `move_card`).
- **Um `Board` pertence sempre a UMA orquestração** — não existe hoje
  agregação de backend cruzando cards de várias orquestrações (o kanban
  macro, `/ui/`, faz essa agregação inteiramente no cliente).

Duas decisões foram confirmadas com o usuário.

## Decisão

**(1) `/ui/kanban?id=` é o board de UMA demanda** (opção recomendada,
aprovada) — mesmo padrão de `/ui/documentos?id=` (FID-19): página fixa da
sidebar (`ROTULOS_WIREFRAME`/seção "Kanban", placeholder desde o FID-09),
sem `id` mostra um seletor de demandas. Não agrega múltiplas orquestrações
— o kanban macro (`/ui/`) continua sendo essa visão, intocado.

**(2) Máquina de estados implementada de verdade** (opção recomendada,
aprovada) — novo módulo puro `kanban/transitions.py`: grafo
`TRANSICOES_VALIDAS: dict[ColumnKey, frozenset[ColumnKey]]`, derivado do
diagrama do §35 com os nomes mapeados para `ColumnKey` reais. Os dois
estados sem `ColumnKey` própria (Rollback, Pronto para implantação) são
**colapsados nas arestas reais adjacentes** (`REVIEW→DEPLOYING` direto;
`VALIDATING→NEEDS_FIX` direto) — decisão explícita, documentada, não uma
perda silenciosa de informação. `WAITING_AGENT`/`FAILED`/`ARCHIVED` não têm
nenhuma aresta manual definida — não aparecem no wireframe nem na
automação real (`_EVENT_TRANSITIONS`), então o grafo não fabrica uma
permissão que não corresponde a nenhum fluxo real.

**(3) Validação só no caminho MANUAL de movimentação — automação interna
continua livre.** Investigação confirmou que **todo** call-site interno de
`move_card` (roteamento de falha, liberação de dependência, automação por
evento, `block_card`/`unblock_card`/`cancel_card`) chama
`BoardService.move_card` **diretamente**, nunca através do método de
serviço `OrchestrationService.move_card`. O único caminho real que passa
por `OrchestrationService.move_card` é o endpoint HTTP `POST .../move`
(usado hoje pelo botão de mover em `detalhe.html` e, agora, pelo
drag-and-drop desta tela). Por isso: novo método
`OrchestrationService.move_card_validado` (valida a transição, senão
delega a `board_service.move_card` sem mudança) — só o endpoint HTTP passa
a chamá-lo; `OrchestrationService.move_card` (sem validação) continua
existindo e é usado como está por quem já o chama diretamente em Python
(alguns testes usam-no como atalho de fixture, sem testar a máquina de
estados em si). Zero risco à automação interna, já madura e testada.

**(4) Dois testes existentes precisaram de ajuste** — `test_card_ops_assign_move_block_unblock`
e `test_get_card_events_reflete_movimentacoes` moviam cards via o endpoint
HTTP para uma coluna arbitrária não alcançável em um salto desde o estado
inicial real do card (`Ready` para cards seed, `Backlog` para cards criados
via `POST .../cards`) — não estavam testando a máquina de estados, só
usando o endpoint como forma conveniente de mudar o status para testar
outra coisa (a cadeia assign→move→block→unblock; o registro de
`CardEvent`). Corrigidos para usar a transição válida mais próxima
(`InProgress`/`Planning`), preservando a intenção original de cada teste.

**(5) `GET /v1/orchestrations/{id}/kanban` novo — as 16 colunas reais, cada
uma com o rótulo do wireframe quando existe** (13 das 16 têm; as 3 sem
correspondência usam o próprio nome do `ColumnKey`), **e os cards com os
11 campos do §13.3 já resolvidos no backend** (agente/modelo/effort
cruzados com o catálogo de executores e o ring de tentativas; aprovação
humana pendente já filtrada por `card_id`) — evita N+1 de chamadas no
cliente para montar cada card.

**(6) Drag-and-drop nativo (HTML5), sem biblioteca externa** — mesmo
precedente "zero dependência" das ADRs anteriores. Transição rejeitada
mostra a mensagem real devolvida pelo backend (não um texto genérico) e
recarrega o quadro para refletir o estado real (o card "volta" para a
coluna de origem visualmente porque o quadro é sempre re-buscado do
servidor após qualquer tentativa de movimento, nunca movido otimisticamente
no cliente antes de confirmação).

## Consequências

**Positivas**
- Paga uma dívida de spec de 2 fases atrás (TASK-04/ADR-0002), não é escopo
  extra inventado.
- Zero risco à automação interna — nenhum call-site de produção fora do
  endpoint HTTP foi tocado.
- `updated_at` já era, sem nenhuma mudança, um proxy correto de "tempo na
  etapa" (confirmado como o único campo mutado exclusivamente por
  `move_card`) — nenhum campo novo de timestamp foi necessário.

**Negativas / riscos aceitos**
- "Pronto para implantação" e "Rollback" (do diagrama §35) não aparecem
  como colunas/estados visíveis próprios — documentado, não escondido.
- Contagem de falhas no card resumido usa o ring (`len(card.failures)`,
  travado em 5) — um card com mais de 5 falhas reais mostra "5+", não o
  total exato (mesma limitação já documentada em cards anteriores que leem
  esse ring).
- `move_card` (sem validação) continua acessível diretamente em Python —
  qualquer código futuro que o chame fora do endpoint HTTP não passa pela
  máquina de estados. Aceito conscientemente: é o mesmo método que a
  automação interna precisa continuar usando livremente.
