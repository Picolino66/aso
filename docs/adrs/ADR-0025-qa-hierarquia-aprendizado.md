# ADR-0025 — QA humano, hierarquia de cards e aprendizado da esteira

- **Status:** ACCEPTED
- **Fase:** F5/F7 (evolução pós-O5)
- **Data:** 2026-07-31
- **Relaciona-se com:** [ADR-0017](ADR-0017-revisao-independente-de-codigo.md)
  (`exige_confirmacao_humana`, molde de `exige_qa_manual`), [ADR-0018](ADR-0018-kanban-fiel-colunas-e-dependencias.md)
  (dependente de card cancelado nunca fica órfão — mesmo raciocínio ao
  cancelar um pai), [ADR-0019](ADR-0019-roteamento-de-falha.md) (roteamento de
  falha, reaproveitado sem taxonomia nova), [ADR-0021](ADR-0021-especificacao-e-revisao-documental.md)
  (`SpecWorkItem`, emendada aqui), [ADR-0022](ADR-0022-bateria-de-validacoes-e-effort-automatico.md)
  (pendência do §9 nomeada e fechada aqui), [`fluxo.md`](../../fluxo.md) §7,
  §9, §16, §17, §24, [`plano6.md`](../../plano6.md) §1

## Contexto

Depois do Incremento F (ADR-0023) e da correção da corrida de candidatos
(ADR-0024), restavam três seções do `fluxo.md` e uma pendência nomeada três
vezes (plano4 §2.4, plano5 §2.4, ADR-0022):

- **§16/§17 — QA manual**: nunca existiu nada. Busca por `teste_manual`/`QA`/
  `aceite de negócio` em `src/` só retornava `acceptance_criteria`, que é
  outra coisa (critério do card, não passo de validação).
- **§7 — hierarquia épico → história → subtarefa**: `CardType` já tinha
  `EPIC`/`FEATURE`, mas `KanbanCard` não tinha `parent_id` e nenhum caminho de
  criação produzia card que não fosse `TASK`.
- **§24 — aprendizado**: `metrics.py`/`slo_report` eram só observacionais;
  nada agregava por executor e nada realimentava decisão.
- **§9 — escolha automática de agente**: a ADR-0022 automatizou o *effort*
  mas deixou registrado que a escolha de *agente/perfil de executor* seguia
  manual "até haver sinal suficiente".

Esta ADR fecha as três primeiras e declara formalmente a quarta como decisão
de não fazer — não como pendência aberta.

## Decisão

### 1. QA manual (§16/§17) — `control/qa.py`

`QaCheck` (cenário, passos, ambiente, resultado esperado/obtido, evidências,
gravidade, status, responsável, tipo de responsável) persiste em
`KanbanCard.qa_checks` — ring de 10, mesmo raciocínio de `card.failures`
(dict solto, não o tipo Pydantic, para não inverter a dependência `control` →
`kanban`).

`exige_qa_manual(brief, card)` é pura, no mesmo molde de
`exige_confirmacao_humana` (ADR-0017): exige QA quando o domínio da ficha
inclui `frontend`, quando `complexidade` é `complexa`/`estrategica`, ou
quando o card é `Epic`/`Feature`. Fora disso, QA continua **opcional** — o
operador pode registrar uma verificação a qualquer momento; a regra só decide
o que o `next_step` cobra antes de liberar a implantação.

**§17 — falha vira bug, sem taxonomia nova.** `fail_qa_check` marca o
`QaCheck` como `falhou`, cria um card `Bug` com `dependencies=[card original]`
e, quando a profundidade da hierarquia permite (ver §2 abaixo),
`parent_id=card original`; a descrição é montada dos passos/resultado/
evidências/gravidade do check. Em seguida registra um `FailureRecord`
(`categoria="qa"`) no **card original** e chama `diagnosticar`/`decidir`
(`control/failure.py`, ADR-0019) — o retorno "depende do tipo de falha" (§17)
não ganhou taxonomia própria: um novo diagnóstico `falha_de_qa` entra na
tabela existente, com política `mesmo_agente → aumentar_effort →
escalar_humano`, mais paciente que uma falha de teste automatizado porque nem
toda reprovação de QA é regressão de código. O card original vai para
`NeedsFix` (mesmo agente/effort) ou `Failed` (escalou para humano) — mesmo
par de colunas que `_route_failure` já usa para falha de execução.

`next_step.py` ganha `_qa_blocker`: olha o **último** `QaCheck` de cada card
(um novo registro depois de uma reprovação resolve o bloqueio sozinho, sem
precisar "fechar" o item antigo) —

- `falhou` → `qa_reprovado` (`bloqueia`);
- nenhum check ainda e `exige_qa_manual` verdadeiro, card em
  `Testing`/`Review`/`Done` → `qa_pendente` (`aguardando_humano`).

Cards `Cancelled`/`Archived` nunca entram. API: `GET`/`POST
.../cards/{id}/qa` (viewer/operator) e `POST .../cards/{id}/qa/{i}/fail`
(operator — nenhuma mudança em `api/auth.py`, o corpo já não exige papel
especial para reprovar QA).

### 2. Hierarquia épico → história → subtarefa (§7) — `kanban/hierarchy.py`

`KanbanCard.parent_id: str | None = None` — nulo é o estado de todo card
existente e continua válido, a hierarquia é opcional. As quatro regras vivem
em funções **puras** sobre `dict[str, KanbanCard]` (`kanban/hierarchy.py`,
testadas isoladamente sem precisar de `BoardService`), usadas por
`BoardService.add_card`/`move_card`:

- **Profundidade máxima 3** (Epic → Feature → Task) — `add_card` recusa
  (`ValueError`) um card cujo pai já está no nível 3.
- **Ciclo é erro** — `fecha_ciclo` detecta se o novo pai (ou um ancestral
  dele) é o próprio card. Não há hoje uma operação de "reparentar" exposta
  pela API — todo `parent_id` nasce com a criação do card, e um card recém-
  criado nunca é ancestral de ninguém —, então este caminho é defensivo/
  futuro-prova; testado diretamente na função pura, não através de
  `add_card`.
- **Pai não fecha antes dos filhos** — `move_card` recusa (`ValueError`) uma
  transição para `Done` enquanto houver filho fora de `Done`/`Cancelled`.
- **Cancelar o pai cancela os filhos** — `move_card` para `Cancelled`
  cascateia (`_cancelar_filhos`) para os filhos ainda abertos, recursivamente;
  filho já `Done` fica como está (cancelar não desfaz trabalho concluído).
  Mesmo espírito da ADR-0022 (dependente de card cancelado nunca fica órfão
  em silêncio).

**Quem produz a hierarquia**: `SpecWorkItem` (`control/spec.py`) ganha
`tipo: str = "Task"` e `itens_filhos: list[SpecWorkItem]` — só um nível (uma
história pode ter subtarefas; uma subtarefa com `itens_filhos` preenchido é
ignorada por quem consome, não validado como erro). `_materialize_spec_cards`
cria os cards-raiz primeiro, depois os filhos com `parent_id` resolvido pelo
título do pai — mesma segunda-passada título→id que já resolve `depende_de`.
Se a profundidade máxima seria excedida (card original de uma reprovação de
QA já no nível 3, por exemplo), o bug nasce sem `parent_id` — a `dependencies`
sozinha já vincula, e a criação do bug nunca falha por causa da hierarquia.
`BacklogItem` (`control/planning.py`) ganha `type: str = "Task"` (sem
`itens_filhos` — o caminho de plano do LLM permanece flat; só a spec produz
árvore) para o LLM poder marcar épicos mesmo nesse caminho.

### 3. Aprendizado (§24) — `observability/aprendizado.py`

**Regra de módulo**: `observability` importa só `shared`. O cálculo vive
**puro** em `observability/aprendizado.py` — recebe `CardSnapshot`/
`PullRequestSnapshot` já achatados, nunca importa `control`. Quem coleta o
estado do bundle e monta a entrada é
`OrchestrationService._coletar_aprendizado`/`get_learning_report` — mesmo
arranjo de `next_step.py` (função pura) + `Service.next_step` (coleta), e de
`agent_log` (ADR-0015). Isto é deliberadamente diferente do arranjo antigo de
`metrics.py`, que importa `control.orchestration_service` diretamente
(pré-existente, não corrigido aqui — fora de escopo desta ADR); o agregador
novo não repete esse padrão.

`consolidar(orchestration_id, cards, pulls, *, intervencoes_humanas)` agrega
por executor: execuções, falhas, retrabalho (uma reexecução por falha
registrada), tempo médio (`AgentExecuted.ms` do event log, somado por card),
rodadas de revisão médias, erros recorrentes por categoria. Fontes, todas já
persistidas antes desta ADR:

| Pergunta do §24 | Fonte |
|---|---|
| Retrabalho | `card.failures` (ADR-0019) |
| Falhas por etapa | `FailureRecord.etapa` |
| Desempenho por executor | `card.executor` (ADR-0017) × `card.failures` |
| Tempo gasto | evento `AgentExecuted.ms` |
| Taxa de aprovação | `pr.review_rounds`/`review_status` |
| Intervenções humanas | `HumanApproval` resolvida + `QaCheck` com `tipo_responsavel="humano"` |
| Erros recorrentes | `FailureRecord.categoria` |

`GET /v1/orchestrations/{id}/learning` (uma demanda) e `GET /v1/learning`
(consolidado entre todas, reaproveitando o mesmo `consolidar` com a lista
inteira de cards/pulls achatada — sem uma segunda função de merge).

**Limite deliberado, o mais importante desta parte: o relatório NÃO
realimenta decisão automaticamente.** `recomendacao` é texto para o operador
ler — nunca um campo que outro código consome. O §24 do `fluxo.md` diz que as
informações "podem ser utilizadas" para melhorar decisões futuras: permissivo,
não imperativo. Fechar o laço agora significaria um runtime que muda de
perfil de executor sozinho com base em amostra pequena e enviesada (as falhas
observadas dependem só das demandas que apareceram até agora).

**Escopo não coberto, por decisão**: "effort necessário" (evento
`EffortSugerido` da ADR-0022 vs. effort final) não entra no relatório desta
ADR — o insumo já existe no event log, mas cruzá-lo corretamente por card
exigiria mais uma dimensão de coleta sem um consumidor claro ainda. Registrado
aqui como próximo incremento possível do próprio relatório, não como buraco
escondido.

### 4. §9 — escolha automática de agente: decisão de não fazer

A ADR-0022 automatizou o *effort* e deixou a escolha de *agente* registrada
como pendência "até haver sinal suficiente". Esta ADR declara formalmente:
**não fazer, por ora** — não por esquecimento, por falta de dado. Os papéis
do `AgentRegistry` são funcionais (backend, frontend, dados) e o mapeamento
domínio → papel já existe em `_DOMAIN_AGENTS` desde sempre; o que falta é
escolher entre **perfis de executor** (`claude-opus` vs. `codex-high`), e para
isso não havia dado até este incremento. Agora há: `desempenho_por_executor`
do relatório de aprendizado é exatamente o insumo que faltava. Fazer a
automação antes dos dados seria adivinhar; fazer depois é decidir. Reavaliar
quando o relatório tiver massa de várias demandas reais — o `GET /v1/learning`
consolidado existe precisamente para isso.

## Consequências

**Positivas**
- `fluxo.md` §7, §16, §17, §24 fecham dentro do escopo real do MVP — sem
  inventar taxonomia (`falha_de_qa` reaproveita a tabela de roteamento
  existente), sem inventar um segundo mecanismo de versionamento (a
  hierarquia usa `parent_id` direto, não um ring), sem fechar o laço do
  aprendizado por conta própria.
- Pendência do §9 nomeada em três documentos anteriores sai da lista, com
  decisão registrada e critério explícito de quando reavaliar.
- `card.failures` ganha uma nova origem (`categoria="qa"`) sem exigir nenhuma
  mudança em `diagnosticar`/`decidir` além de uma entrada na tabela — a
  reutilização provou o desenho da ADR-0019.
- `observability/aprendizado.py` não importa `control` (verificado por teste
  de import, não só por convenção).

**Negativas / riscos aceitos**
- **Ciclo na hierarquia é defensivo, não exercitado pelo caminho real** — não
  há hoje uma operação de reparentar exposta pela API; se uma futura
  funcionalidade adicionar uma, `fecha_ciclo` já está pronta e testada, mas o
  caminho ainda não tem chamador real.
- **QA continua sem exigir um passo bloqueante no `merge_pr`** — `qa_pendente`/
  `qa_reprovado` aparecem como bloqueio de `next_step`, mas nada no código
  impede um merge governado de acontecer com QA pendente; a governança é
  informativa/visível, não um gate hard-coded no merge. Mesmo princípio do
  gate de implantação (ADR-0023): o runtime não trava o que não tem certeza
  de dever travar.
- **Aprendizado não cobre "effort necessário"** (ver §3 acima) — registrado
  como corte consciente, não esquecido.
- **UI**: painel de QA em `index.html` reaproveita `prompt()`/`confirm()`
  (mesmo padrão já usado por rollback/aprovação com justificativa) em vez de
  um formulário dedicado — suficiente para operar, mais simples que inventar
  um segundo componente de formulário.

## Escopo cortado

Nenhum corte foi necessário na ordem planejada (aprendizado → hierarquia →
QA, do menos ao mais dependido) — as três partes entraram inteiras. A Parte 0
(corrida de candidatos) está em [ADR-0024](ADR-0024-corrida-de-candidatos-broken-pipe.md).

## Emenda (2026-08-04, ADR-0026)

A premissa da §4 mudou: "não havia dado até este incremento" deixa de ser
verdade a partir da [ADR-0026](ADR-0026-custo-real-e-orcamento.md), que
captura o custo real por execução e acrescenta `custo_por_entrega` ao
relatório de aprendizado — exatamente o critério de "custo" que o `fluxo.md`
§9 lista ao lado de tempo e confiabilidade. A decisão de não automatizar a
escolha de agente/perfil de executor **permanece em vigor** (nenhum código
passou a decidir sozinho); o que muda é que ela agora é **reavaliável com
dado real**, não mais bloqueada por falta dele.
