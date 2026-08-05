# ADR-0026 — Custo real do agente e orçamento com freio

- **Status:** ACCEPTED
- **Fase:** F5/F6/F7
- **Data:** 2026-08-04
- **Relaciona-se com:** [ADR-0015](ADR-0015-observabilidade-ao-vivo-da-execucao.md)
  (mesma solução de porta em `shared` para não inverter `execution`→`observability`),
  [ADR-0019](ADR-0019-roteamento-de-falha.md) (roteamento de falha, onde o freio
  intercepta), [ADR-0021](ADR-0021-especificacao-e-revisao-documental.md) (ficha de
  encerramento, §23, ganha o custo), [ADR-0025](ADR-0025-qa-hierarquia-aprendizado.md)
  (relatório de aprendizado e a decisão do §9, emendada aqui), [`fluxo.md`](../../fluxo.md)
  §9, §13, §24, §26A.11, [`plano7.md`](../../plano7.md) §1, §3.1, §3.2

## Contexto

`observability/metrics.py` documentava, na própria docstring, que "o custo é
aproximado pelo tempo de execução (ms)". Tempo é um proxy ruim: um
`claude-opus` em effort alto custa ordens de grandeza mais por segundo que um
`haiku`, e duas execuções de 30s podem diferir em 50× no valor pago. O dado
real já chegava e era descartado — `agent_stream.py` lia só o `result`/`text`
do envelope final do Claude Code, ignorando `usage`/`total_cost_usd`, que o
próprio CLI informa.

Consequência mais séria: o roteamento de falha (ADR-0019) escala effort e
troca de executor sem nenhum teto de gasto. Um card que falha por um motivo
fora do alcance do agente sobe de effort, troca de executor e reexecuta —
com agentes reais, isso é dinheiro saindo enquanto ninguém olha, e o limite
existente (`ASO_MAX_ESCALONAMENTOS`) conta **tentativas**, não valor.

## Decisão

### 1. Captura de custo real — `shared/agent_usage.py` + `execution/agent_stream.py`

Mesma solução da ADR-0015: a porta (`UsoDoAgente`) vive em `shared` porque
`execution` (quem produz, `agent_stream.extrair_uso`) não pode importar
`observability` (quem consome, `aprendizado.py`) — `control` faz a fiação.

`extrair_uso(linha)` lê o envelope `type == "result"` do Claude Code:
`usage.{input_tokens, output_tokens, cache_read_input_tokens,
cache_creation_input_tokens}` e `total_cost_usd`, conforme o schema
documentado pela Anthropic. Como todo parser de envelope de CLI neste
runtime (mesma disciplina da ADR-0015), reconhece só o que conhece e
devolve `None` no resto — Codex (`exec --json`) não documenta uso/custo no
envelope observado até hoje, cai em `None` como qualquer schema
desconhecido. **A fixture de teste usa o schema documentado, não uma
captura real** (diferente de `test_agent_stream.py`, que tem captura real) —
o runtime ainda não rodou uma demanda real com `usage` populado; o roteiro
manual deste incremento (verificação, passo 1) é quem fecha essa lacuna.

`origem="agente"` vs. `origem="indisponivel"` é a distinção central: **custo
zero e custo desconhecido não são a mesma coisa**. Confundi-los faria o
relatório dizer que uma execução foi grátis quando na verdade ninguém sabe
quanto custou.

`CliAgentExecutionProvider._rodar` varre as linhas de stdout já capturadas
(a última linha com uso reconhecido vence — o envelope `result` do Claude
Code sai por último, mas não custa varrer tudo) e devolve o `UsoDoAgente` em
`AgentOutput.artifacts["uso"]`. `OrchestrationService._execute_isolated`
lê dali e acrescenta `tokens`/`custo_usd`/`modelo`/`uso_origem` ao payload de
`AgentExecuted`; `_apply_execution` acumula em `KanbanCard.uso` via
`acumular_uso` (soma reexecuções, nunca substitui — `execucoes_sem_custo`
conta separado de `execucoes`, sem nunca somar zero por omissão).
`_build_card_closure` (§23, ADR-0021) passa a incluir `custo_usd`/`modelo`
quando disponíveis — campo sem dado continua ausente, não inventado (mesmo
princípio que já regia a ficha).

`observability/metrics.py::execution_timeline` ganha `total_custo_usd` por
card, com a docstring corrigida: tempo é **fallback declarado**, não custo.

### 2. Orçamento com freio — `control/orcamento.py`

`avaliar_orcamento(gasto_usd, teto_usd) -> (situacao, motivo)` é pura:
`ok` / `alerta` (≥ 80% do teto) / `estourado` (≥ 100%). Sem teto configurado
(`None` ou ≤ 0), sempre `ok` — orçamento é **opt-in**, nenhuma orquestração
existente muda de comportamento. `Orchestration.orcamento_usd: float | None`
(novo campo); `ASO_ORCAMENTO_PADRAO_USD` preenche o default de orquestrações
**novas** em `create_orchestration` — sem a env, `None`.

`OrchestrationService._gasto_usd(b)` soma `card.uso.custo_usd` de todo card
do board — o mesmo número que o relatório de aprendizado usa.
`_recusar_se_orcamento_estourado` é chamado na **entrada** de `run_card` e
`race_card` (mesmo ponto onde o kill-switch `cancelled` já recusa): estourado
levanta `ValueError` **antes** de qualquer execução começar. Isto é
deliberado — matar um agente no meio deixaria worktree sujo e trabalho pela
metade, o que custa mais do que economiza. O freio bloqueia **execução
nova**, nunca interrompe a que já está rodando.

**O ponto central do incremento**: dentro de `_route_failure`, depois que
`decidir` (ADR-0019) já escolheu `aumentar_effort` ou `trocar_executor` —
os dois passos que gastariam mais —, o orçamento é consultado; estourado
faz a decisão virar `escalar_humano` com motivo `"orçamento esgotado — ..."`.
É o freio que não existia: sem ele, a política escalaria para o modelo mais
caro justamente quando as coisas já estão dando errado. `mesmo_agente`
(retry sem trocar de perfil) e `bloquear` não são afetados — não gastam mais
que a tentativa anterior.

`next_step.py` ganha `_budget_blocker`: `orcamento_estourado`
(`bloqueia`, ação `PUT .../budget` exigindo `admin`) e `orcamento_em_alerta`
(`informativo`, mesma ação). `set_orcamento` (endpoint `PUT
.../orchestrations/{id}/budget`) é a única forma de elevar/remover o teto —
**exige `admin`** (`/budget` entra no sufixo administrativo de
`api/auth.py`), mesmo espírito da regra 4 do CLAUDE.md: autorizar mais gasto
é decisão humana.

### 3. Relatório de aprendizado — `observability/aprendizado.py`

`DesempenhoPorExecutor` ganha `custo_total_usd`, `custo_por_entrega`
(`custo_total_usd` dividido pelas execuções que chegaram a `Done` — nunca
pelo total de execuções, com guarda de divisão por zero) e
`execucoes_sem_custo`. **Nunca compare custo bruto entre executores sem
dividir por entrega**: um executor caro que entrega de primeira pode sair
mais barato que um barato que precisa de três tentativas — registrado
explicitamente na UI (`renderLearning`, `index.html`) e no docstring do
módulo.

### 4. Emenda à ADR-0025 — §9 deixa de estar congelado

A ADR-0025 declinou a escolha automática de agente/perfil de executor "por
falta de dado" — `custo_por_entrega` é exatamente o dado que faltava
(o `fluxo.md` §9 lista "custo" entre os critérios de escolha, ao lado de
tempo e confiabilidade, que já existiam). **Este incremento não implementa
o §9** — só remove o motivo pelo qual foi adiado. A decisão de automatizar
segue sendo do operador, sobre dados agora disponíveis via `GET
.../learning`.

## Consequências

**Positivas**
- O relatório de aprendizado deixa de usar tempo como proxy de custo quando
  há dado real — sem quebrar quem nunca teve `usage` disponível (fallback
  declarado, não silencioso).
- O roteamento de falha ganha o único freio que faltava para operar com
  dinheiro real, sem tocar a tabela de política pura da ADR-0019 (o freio
  intercepta a decisão já tomada, não reescreve `decidir`).
- Zero regressão: sem `ASO_ORCAMENTO_PADRAO_USD` e sem `PUT .../budget`,
  toda orquestração se comporta exatamente como antes deste incremento.

**Negativas / riscos aceitos**
- **O parser de `usage` do Claude Code não foi verificado contra saída real**
  (schema documentado, não capturado) — risco já registrado explicitamente;
  o roteiro manual deste incremento é quem fecha essa verificação na
  primeira execução real.
- **Custo de uma tentativa que FALHOU não é capturado** — `_uso_do_output`
  só lê `artifacts["uso"]` de um `AgentOutput` bem-sucedido; uma execução que
  o CLI cobrou mas terminou em erro (diff vazio, timeout) não soma ao total.
  Corte consciente: capturar custo de falha exigiria expor `usage` também no
  caminho de exceção de `CliAgentExecutionProvider.execute`, fora do escopo
  deste incremento.
- **`_gasto_usd` soma todo o board a cada chamada de `run_card`/`race_card`**
  — O(nº de cards) por chamada; aceitável na escala atual (dezenas de cards
  por orquestração), não otimizado com um contador incremental.

## Escopo cortado

Nenhum — Partes 1 e 2 do `plano7.md` entraram inteiras (o próprio plano
marca as duas como "não corte": juntas são a razão de existir do
incremento). Parte 3 (sobrevivência a crash) está na [ADR-0027](ADR-0027-sobrevivencia-a-crash.md).
