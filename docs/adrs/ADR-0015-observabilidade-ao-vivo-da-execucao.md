# ADR-0015 — Observabilidade ao vivo da execução e esteira legível

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-07-29
- **Relaciona-se com:** [ADR-0009](ADR-0009-entrega-de-codigo-governada.md) (worktree
  isolado), [ADR-0013](ADR-0013-tela-de-detalhe-por-proximo-passo.md) (tela por próximo
  passo), [ADR-0014](ADR-0014-agente-por-etapa-e-nomes-semanticos.md) (agente por etapa)

## Contexto

A tela de detalhe da ADR-0013 responde "o que falta para a esteira andar". Ela não
responde **"o que está acontecendo agora"** — e essa é a pergunta de quem acabou de
clicar em "rodar fase" e vai esperar dez minutos.

Três causas distintas, com o mesmo sintoma de tela morta:

1. **A saída do agente só existia depois da morte do processo.**
   `subprocess.run(capture_output=True)` lê os pipes em `communicate()`, ou seja, no fim.
   O que sobrava era `artifacts["stdout"][:2000]` — os **primeiros** 2 000 caracteres, e
   `stderr` era descartado inteiro no caminho de sucesso. Nada disso era persistido.

2. **O SSE existente não tem o que transportar.** `EventBroker` é uma fila de `int`, e o
   único `publish` está no middleware HTTP, **depois** da resposta. Um `run-phase` de dez
   minutos emite exatamente um tick, no fim.

3. **A esteira era rótulo, não informação.** `PHASE_LABELS` tem os nomes em inglês, e a
   UI exibia só o da fase corrente. "F1 F2 F3 F4 F5 F6 F7" não diz a ninguém o que cada
   etapa faz — e a escolha de agente por etapa (ADR-0014) ficara escondida atrás de um
   clique no modal de configuração, invisível na prática.

Descoberto ao investigar: o painel "Atividade ao vivo" pedia `timeline?page_size=14` com
`ORDER BY seq ASC` e `offset=0`. Ele mostrava os 14 eventos **mais antigos** da
orquestração — o começo da história — e os invertia no render. A cada tick do SSE
recarregava a mesma fatia errada.

## Opções consideradas

1. **Estender o `EventBroker` para carregar payload.** Rejeitada. Ele é `asyncio.Queue`
   sem lock e descarta em `QueueFull`; publicar da thread do agente exigiria
   `loop.call_soon_threadsafe` com o loop capturado no startup. Coalescer *ticks* é
   correto; **perder linhas de log não é**. Além disso o SSE não dá replay: quem
   recarregasse a página no meio da execução perderia tudo o que já passou.

2. **Guardar a saída no `EventLog`.** Rejeitada. O repositório faz delete + reinsert de
   todas as tabelas filhas em cada `save`; centenas de linhas por card custariam O(n) de
   escrita por mutação. Log de execução é telemetria, não estado governado.

3. **Coluna nova em `kanban_cards` com a cauda do log.** Rejeitada por ora — mesma
   amplificação de escrita, em troca de sobreviver a um restart da API.

4. **Ring buffer em memória + leitura por cursor.** Escolhida.

## Decisão

### (1) Porta em `shared`, ring em `observability`, produção em `execution`

`shared/agent_output.py` define o vocabulário (`STREAM_*`, `KIND_*`) e dois Protocols
estruturais — `OutputSink` (destino de uma execução) e `OutputBus` (abre sinks). Isso é
exigência da regra de dependência (`module_map`): `execution`, que **produz** a saída, só
pode depender de `shared` e `agents`; o ring, que a **consome**, vive em `observability`.
Ports & Adapters: porta em `shared`, adapter em `observability.agent_log`, fiação em
`control`.

`AgentLogBus` mantém um `deque(maxlen=2000)` por orquestração com cursor monotônico, sob
`threading.Lock` — produtor é a thread do agente, consumidor é o handler HTTP.
`AgentLogSession` é context manager: fechar registra desfecho e duração **mesmo em
exceção**, para a UI nunca ficar com um `running: true` órfão consultando para sempre.

A leitura é **polling com cursor** (`GET .../agent-log?after=<seq>`), não push. Mais
simples, não perde linha, e dá replay: recarregar a página no meio da execução reexibe o
que já passou. Latência de ~900 ms é indistinguível de streaming para ler texto.

O preço é explícito: **o log morre ao reiniciar a API.** É telemetria de acompanhamento.
O que precisa sobreviver — falha, motivo, diff — continua no `EventLog` e no
`block_reason` do card.

### (2) Leitura incremental do subprocess

`subprocess.run` → `Popen` + **uma thread de bombeamento por pipe**. Duas threads em vez
de `selectors` (o padrão que `codex_discovery.py` já usa) porque mantêm `stdout` e
`stderr` separados — o motivo de falha prefere o stderr — e eliminam o deadlock de um
pipe cheio enquanto se lê o outro.

**Timeout, que não existia.** Era o único subprocess do repositório sem limite: um CLI
parado esperando permissão interativa prendia uma thread do servidor e um worktree para
sempre. `ASO_AGENT_TIMEOUT` (default 1800 s) é rede de segurança, não bound apertado; ao
estourar, mata o processo e levanta `AgentExecutionError` com a cauda capturada.

`artifacts["stdout"]` passa a guardar os **últimos** 4 000 caracteres, não os primeiros —
o desfecho é o que interessa depois.

### (3) Interpretação do NDJSON

Aqui está o achado que muda a expectativa: **`claude -p` imprime só a resposta final.**
Streaming do nosso lado não cria narração; quem emite evento por evento é o CLI, com
`--output-format stream-json --verbose` (Claude) ou `--json` (Codex).
`scripts/enable-agent-stream.sh` acrescenta essas flags ao catálogo, de forma idempotente.

`execution/agent_stream.py` é uma função **pura** que traduz cada linha: blocos `text` e
`thinking` viram fala, `tool_use` vira "🔧 Write src/app.js", `result` vira desfecho.
Duas regras vêm da saída **real** capturada de uma execução (não de suposição): o
envelope inclui `system`/`rate_limit_event`, que sem uma lista de ruído apareceriam como
JSON cru na tela; e `thinking` sai longo e em inglês, então é cortado em 140 caracteres
para não empurrar as ações para fora do painel.

Princípio: **nunca inventar**. O schema do `--json` do Codex varia entre versões; o parser
reconhece o que conhece e devolve `bruto`, com o texto preservado, para tudo o mais. Um
formato novo degrada para "mostra como veio", nunca para linha perdida ou exceção.

O mesmo parser destila o `block_reason` do card (`extrair_texto`): com NDJSON ligado, sem
isso o motivo da falha seria uma parede de JSON — e o raciocínio interno, que não explica
nada ao operador, é excluído.

### (4) Esteira que ensina e configura

`PHASE_INFO` (ao lado de `PHASE_LABELS`, que permanece) dá a cada fase `nome`, `resumo` e
`entrega` em pt-BR, genéricos para qualquer projeto — os `docs/phases/*.md` documentam o
desenvolvimento do próprio ASO, não o significado das etapas. Exposto em `GET /v1/phases`
para a UI não duplicar texto.

Cada fase da esteira passa a ser um cartão com nome, descrição, o que entrega e um **chip
de agente clicável** que faz `PUT`/`DELETE .../agents/{key}`. A escolha por etapa da
ADR-0014 sai do modal e vai para onde o operador olha. Fases concluídas ficam
desabilitadas — a regra já recusava com 409; a UI apenas antecipa.

### (5) Correção da ordem da timeline

`events_page` ganha `newest_first`, aplicado **no banco**. Reordenar depois só embaralharia
a mesma fatia errada.

## Consequências

**Positivas**
- O operador vê o agente trabalhando, ferramenta por ferramenta, e para de olhar tela morta.
- Um agente travado agora morre em 30 min em vez de prender thread e worktree para sempre.
- Falha de card traz a fala do agente legível, não JSON.
- "F1" deixa de ser sigla; a escolha de agente por etapa fica visível.

**Negativas / riscos aceitos**
- O log não sobrevive a restart da API (opção 3 fica registrada se isso incomodar).
- Sem TTY, um CLI arbitrário pode continuar bufferizando em blocos de 4-8 KB; o NDJSON
  resolve para Claude e Codex, mas não é garantia universal.
- O polling gasta uma requisição por segundo por aba aberta durante a execução.
- A adesão do parser ao Codex depende da versão do CLI; foi verificada apenas contra o
  envelope do Claude Code.
