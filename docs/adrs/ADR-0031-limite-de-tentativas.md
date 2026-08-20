# ADR-0031 — Limite de tentativas por card e correção do contador

- **Status:** ACCEPTED
- **Fase:** F5 (execução, roteamento de falha)
- **Data:** 2026-08-06
- **Relaciona-se com:** [ADR-0019](ADR-0019-roteamento-de-falha.md) (roteamento de falha —
  esta ADR corrige um bug na contagem de tentativas que ela introduziu, não muda a
  tabela de política), [ADR-0028](ADR-0028-regras-de-roteamento.md) (`RoutingRule.acao.
  limite_tentativas`, persistido mas nunca aplicado — fechado aqui), [`wiframe-fluxo.md`](../../wiframe-fluxo.md)
  §36.4

## Contexto

`wiframe-fluxo.md` §36.4 pede, por card: número máximo de tentativas, número
atual de tentativas, histórico de falhas, regras de escalonamento. A investigação
para este card encontrou mais que uma lacuna de funcionalidade — encontrou um
**bug real** já latente em produção.

### O bug: contador de tentativas confundido com tamanho do ring

`control/failure.py::decidir` já aceita `max_escalonamentos` e checa `tentativa >
limite` antes de qualquer decisão baseada em diagnóstico. Os pontos de chamada
por card (`_route_failure`, `fail_qa_check`) sempre passavam `self.
_max_escalonamentos` (o teto global do processo) — nunca algo configurável por
card; essa era a lacuna esperada. O problema mais sério, encontrado na
investigação: os dois usavam `len(card.failures)` como o argumento `tentativa`
— e `card.failures` é um **ring travado em 5** (`registrar(card.failures,
record)` nunca recebia `limite=` diferente do default).

Hoje, toda tabela de política em `_TABELA` tem no máximo 4 passos e termina em
`escalar_humano` — então, dentro de **uma única chamada** a `run_card` (que
re-tenta internamente até a decisão parar de ser retentável), o card sempre
escala bem antes de a diferença entre `len(card.failures)` e a contagem real
aparecer; por isso a lacuna não muda o *timing* da primeira escalação. Ela
aparece — de forma real e visível — no cenário coberto por `POST .../route`
(reroteamento manual **repetido** sobre um card já `Failed`, ex.:
`test_get_failures_e_post_route_pela_api`): cada chamada soma **mais uma**
entrada a `card.failures`, e depois da 5ª o ring começa a descartar as mais
antigas — o rótulo "tentativa N" que `next_step` monta a partir de `len(card.
failures)` **trava em "tentativa 5" para sempre**, não importa quantas vezes o
operador reroteie manualmente depois disso. É um bug de contagem real, hoje
visível na UI/`next_step`, não uma falha silenciosa de escalação (a escalação
em si sempre acontecia — o Princípio central nunca foi violado na prática) —
mas ainda assim o oposto do que "número atual de tentativas" (§36.4) promete:
um contador que para de contar.

## Decisão

### 1. Contador autoritativo, separado do ring de auditoria

`KanbanCard.tentativa_atual: int = 0` — inteiro simples, **nunca truncado**,
incrementado a cada execução real (sucesso ou falha) em `_apply_execution`
(sucesso) e `_route_failure`/`fail_qa_check` (falha). É o único valor passado a
`decidir(...)` a partir de agora — `len(card.failures)` deixa de ser usado como
contador em qualquer lugar do código (só continua existindo para o que sempre
foi: o ring de auditoria das últimas 5 falhas, ADR-0019, intocado).

`_route_failure`/`fail_qa_check` incrementam o próprio contador internamente
(não dependem de o chamador incrementar antes) — mantém as duas funções
autocontidas, do mesmo jeito que o cálculo antigo `len(card.failures) + 1` já
era. Confirmado por regressão: `tests/unit/test_orcamento_freio.py` chama
`svc._route_failure(...)` diretamente, sem passar por `_apply_execution` — se o
incremento dependesse do chamador, esses testes quebrariam (quebraram numa
primeira tentativa desta implementação, corrigido revertendo para
autocontido).

### 2. `max_tentativas` por card — `None` preserva o comportamento de sempre

`KanbanCard.max_tentativas: int | None = None`. `_route_failure`/`fail_qa_check`
resolvem o teto efetivo como `card.max_tentativas if card.max_tentativas is not
None else self._max_escalonamentos` — card sem teto próprio continua usando o
global, byte a byte o comportamento de toda orquestração anterior a esta ADR
(prova: suíte completa, 927 testes, sem nenhuma alteração de resultado).

### 3. Histórico por tentativa — sucesso E falha, não só falha

`card.failures` (ADR-0019) é estritamente um log de **falhas**. O §36.4 pede
"modelo/effort/resultado" por tentativa — incluindo a tentativa que finalmente
teve sucesso, que `failures` nunca registra. Novo módulo puro
`control/attempts.py`: `TentativaRegistro` (`numero`, `executor`, `effort`,
`resultado` sucesso|falhou, `diagnostico`, `at`) + `registrar_tentativa` (ring,
mesmo padrão de `control/failure.py::registrar`), persistido em
`KanbanCard.tentativas: list[dict] = []` (ring de 10 — maior que o de falhas
porque agora inclui sucesso, então enche mais rápido em cards saudáveis).

### 4. `RoutingRule.limite_tentativas` — fecha a pendência da ADR-0028

`RoutingAction.limite_tentativas` já existia (ADR-0028) mas nunca era lido.
Novo helper `_max_tentativas_da_regra(orchestration) -> int | None` lê
`orchestration.routing_rule_applied["acao"]["limite_tentativas"]`. Diferente de
`acao.agente`/`modelo` (que só tocam `plan.agents[0]`/campos globais da
orquestração), o limite de tentativas se aplica a **todos** os cards nascidos
na mesma leva — a regra decide sobre o perfil de risco da *demanda*
("segurança crítica → no máximo 3 tentativas"), não sobre um agente específico.
Aplicado nos três pontos de criação de card (`create_orchestration`,
`populate_from_plan`, `_card_de_spec_item`/`_materialize_spec_cards`) para
cobrir os três caminhos de povoamento do board, não só o principal.

### 5. `next_step` — mostra o contador certo

`_cards_falhos_blocker` trocou `len(card.failures)` por `card.tentativa_atual`
no `detail`, e passa a mostrar "tentativa N de M" quando `max_tentativas` está
configurado (antes só "tentativa N", sem teto visível).

## Consequências

**Positivas**
- Corrige um bug real e verificável: reroteamento manual repetido (`POST
  .../route`) sobre um card `Failed` incrementa `card.tentativa_atual`
  corretamente para sempre, em vez de o rótulo "tentativa N" travar em 5
  (tamanho do ring) depois da 5ª chamada — `next_step` volta a mostrar a
  contagem real.
- `RoutingRule.acao.limite_tentativas` (ADR-0028) deixa de ser um campo morto
  — agora pode forçar escalação mais cedo (ex.: o exemplo do próprio wf §33.1,
  "limitar a 3 tentativas automáticas" para demanda de segurança crítica).
- Histórico por tentativa passa a incluir sucesso, fechando literalmente o que
  o §36.4 pede ("modelo/effort/resultado" — não só "resultado = falha").
- Zero regressão: suíte completa (927 testes) sem alteração de resultado;
  `card.max_tentativas=None`/`tentativa_atual=0` são os defaults de toda
  orquestração existente.

**Negativas / riscos aceitos**
- O limite de uma `RoutingRule` se aplica à leva inteira de cards nascidos
  junto, não a um card específico — não existe hoje granularidade para "esta
  regra vale só para o card do agente principal, não para os demais". Aceito
  por ser a leitura mais fiel ao espírito da regra (perfil de risco da
  demanda, não de um agente).
- `card.tentativas` (histórico completo) e `card.failures` (só falhas)
  guardam informação parcialmente sobreposta — aceito porque servem públicos
  diferentes (auditoria de falha vs. histórico completo do §36.4) e nenhum dos
  dois pode ser removido sem quebrar contrato existente (`failures` já é
  consumido por `diagnosticar`/UI).
- `_gate_retry_targets` (retry por fase, não por card) não foi tocado —
  continua usando seu próprio contador (`b.gate_results` da fase), fora de
  escopo deste card (o §36.4 é sobre o card, não sobre a fase inteira).
