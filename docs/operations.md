# Operações — ASO Runtime (Runbook)

> Fase F6. Procedimentos operacionais mínimos. Observabilidade via EventLog/timeline (§33).

## Executar localmente

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python -m aso.cli.main run "Criar módulo X"   # ciclo completo (mock)
uvicorn aso.api.app:app         # API v1 em :8000 (docs em /docs)
```

## Stack completa em Docker (recomendado — sem dependências na máquina)

```bash
docker compose up --build        # sobe Postgres + API (migrations aplicadas no boot)
bash scripts/smoke.sh http://localhost:8000   # smoke end-to-end
docker compose down -v           # derruba tudo e limpa o volume
```

A API fica em `http://localhost:8000` (Swagger em `/docs`). O healthcheck usa `/health`.
Validado localmente contra Postgres real (smoke OK). O mesmo fluxo roda no CI (job `smoke-docker`).

## Banco de dados

- Sem `ASO_DATABASE_URL`: persistência **in-memory** (volátil) — só dev.
- Com `ASO_DATABASE_URL`: SQLite ou Postgres.

```bash
export ASO_DATABASE_URL="postgresql+psycopg://aso:aso@localhost:5432/aso"
docker compose up -d postgres   # sobe o Postgres local
alembic upgrade head            # aplica o schema
```

### Recomeçar do zero

```bash
./scripts/reset.sh              # pergunta antes; --sim pula a confirmação
./scripts/reset.sh --executores # e também apaga o catálogo .aso/executors.json
```

Apaga o volume do Postgres (schema recriado por Alembic), os worktrees órfãos de
`.aso/worktrees` (sempre via `git worktree remove` — `rm -rf` deixaria refs órfãs em
`.git/worktrees`), `.aso/run` e o `aso.db` — resíduo do fallback `sqlite:///aso.db` em
[migrations/env.py](../migrations/env.py), criado por qualquer `alembic` rodado sem
`ASO_DATABASE_URL`.

**Não apaga** a governança versionada do próprio ASO (`.aso/context`, `.aso/kanban`,
`.aso/quality-gates`, `.aso/snapshots`, `.aso/reviews`) nem `.aso/executors.json` — o
catálogo de executores vive em arquivo, fora do banco, então seus perfis Claude/Codex
sobrevivem a qualquer reset. Os repositórios-alvo também ficam intactos: o script lista os
`target_path` **antes** do drop (eles só existem no banco) e imprime o comando de limpeza
de cada um, deixando a decisão com você — essas branches guardam trabalho real.

## Migrations (Alembic)

```bash
alembic upgrade head            # aplicar todas
alembic downgrade -1            # reverter a última
alembic current                 # revisão atual
alembic history                 # histórico
alembic check                   # schema == modelos ORM?
alembic revision --autogenerate -m "descricao"   # nova migration
```

A revisão `f84c2a1d9e30` cria o catálogo relacional. IDs legados são convertidos em
projetos arquivados; conflitos de path ficam sem pasta e precisam de restauração
administrativa. Não remova projetos por SQL: use `DELETE /v1/projects/{id}` para arquivar
e preservar as FKs, ou `POST /restore` para reativar.

## Qualidade (gates locais = CI)

```bash
ruff check src tests && ruff format --check src tests
mypy src
pytest -q --cov=src/aso --cov-fail-under=80
bandit -r src -q                # SAST
pip-audit --skip-editable       # SCA
```

## Autenticação e RBAC (§34)

- Sem `ASO_API_KEYS`: **modo dev** (principal `dev`/`admin`) — só para desenvolvimento.
- Em produção, defina os tokens (papéis: `viewer` < `operator` < `admin`):

```bash
export ASO_API_KEYS='{"TOKEN_ADMIN":{"actor":"alice","role":"admin"},"TOKEN_OP":{"actor":"bob","role":"operator"}}'
curl -H "Authorization: Bearer TOKEN_OP" http://localhost:8000/v1/orchestrations
```

- Leitura (GET) exige `viewer`; escrita exige `operator`; ações críticas (aprovar/rejeitar
  aprovação, rollback, arquivar/restaurar projeto) exigem `admin`. O ator autenticado é
  registrado (ex.: `approved_by` e `ProjectEvent.actor`).
- Públicos (sem token): `/health`, `/metrics`, `/`, `/ui`, `/docs`, `/openapi.json`.

## Execução com agentes CLI reais (MVP-3)

Para executar um agente CLI real (ex.: Claude Code, Codex) em worktree isolado por card:

```bash
export ASO_TARGET_REPO=/caminho/do/repositorio-git      # repo onde os agentes trabalham
export ASO_CLI_COMMAND="claude -p"                       # comando do agente CLI
```

Cada card roda numa branch/worktree própria; o diff é coletado antes de qualquer merge e a
branch principal permanece intacta (§26A.6). Sem essas variáveis, usa-se o provider mock
(determinístico).

### Branches criadas pelo runtime

A branch sai do **título do card**
([ADR-0014](adrs/ADR-0014-agente-por-etapa-e-nomes-semanticos.md)):
`feat/calculadora-basica-a1b2c3d4` — prefixo Conventional Commits pelo tipo do card, slug
do título e sufixo curto de unicidade (obrigatório: `retry` e candidatos concorrentes
criam branches simultâneas para o mesmo card). O diretório do worktree fica em
`.aso/worktrees/<nome-achatado>` dentro do repositório-alvo.

Não há mais o prefixo `aso/`: as branches do runtime **não são distinguíveis por glob**
das branches humanas. Para saber quais são dele, consulte `card.branch` no banco:

```sql
select id, title, branch from kanban_cards where branch is not null;
```

Quem escolhe o agente de cada etapa é `agent_assignments` (F1..F7 + `naming` +
`triagem` + `revisao`), na tela de detalhe → ⚙ Config → "Agente por etapa", ou via
`PUT /v1/orchestrations/{id}/agents/{key}`. Sem escolha por etapa, vale o padrão da
orquestração. O agente `naming` é opcional — sem ele o nome sai do título do card, sem
custo; com ele, qualquer falha cai no nome determinístico e registra `NamingFallback`.

### Agente de triagem da demanda (§1/§2, ADR-0016)

Ao criar uma orquestração, `POST /v1/orchestrations` interpreta `user_request` numa
ficha estruturada (`DemandBrief`) que alimenta o `MultiAgentDecisionEngine` — sem ela o
motor de decisão roda sobre uma constante (sempre `SINGLE_AGENT`, risco `LOW`). O
agente resolve, nesta ordem: `executor` do corpo do `POST` → default do catálogo →
heurística determinística (classificação por palavra-chave, sem custo). Configurar um
agente de triagem (`PUT .../agents/triagem`) melhora a qualidade da ficha, mas **nunca**
é pré-requisito: qualquer falha (timeout, JSON inválido, executor removido do catálogo)
cai na heurística e a ficha resultante mostra `origem: "heuristica"` e
`fallback_reason` preenchido na tela de detalhe. Se a heurística não tiver sinal
suficiente no texto, `perguntas_abertas` aparece em destaque no "Próximo passo" — sem
travar a esteira — e `POST .../brief` re-tria depois que o operador completa a
informação.

### Agente de revisão de código (§14/§15, ADR-0017)

Depois que a CI de uma PR passa, `POST .../pulls/{pr}/review/run` roda o agente de
revisão sobre o **diff real** da branch (`git diff HEAD...branch`) — o revisor só vê o
diff, não o worktree. Ele resolve, nesta ordem: `executor` do corpo do `POST` →
`agent_assignments["revisao"]` → default do catálogo, **desde que diferente do
executor que rodou o card**. Sem configurar nada, não há revisor default: a revisão
recusa com `necessita_humano` e `fallback_reason="nenhum agente revisor configurado"`.

**Diferente do agente de triagem e do nomeador, este NÃO tem fallback "gratuito".**
Naming cai num slug e triagem cai numa heurística — ambos continuam corretos sem
agente. Não existe revisão de código determinística: qualquer indisponibilidade do
revisor (sem agente, timeout, JSON inválido, executor removido do catálogo, mesmo
executor do card) escala para `necessita_humano`, **nunca** aprova sozinha. Configurar
um agente de revisão é o que faz PRs de baixo risco fecharem sem intervenção humana —
sem ele, toda PR depende de `POST .../pulls/{pr}/review` com `justificativa` (papel
`admin`).

Mesmo com o agente aprovando, risco alto ou impacto sensível (`security`, `database`,
`deploy`) na ficha da demanda deixa a PR `review_status: "pending"` — o "Próximo passo"
mostra o bloqueio `pr_review_humana` pedindo confirmação.

### Especificação e revisão documental (§5/§6 do fluxo.md, ADR-0021)

Com o discovery aprovado, `POST .../spec/run` gera a especificação e
`POST .../spec/review` roda a revisão documental sobre ela — **antes** de F5
começar (em `full-pipeline`, `POST .../run-phase` recusa F5 sem spec aprovada,
uma vez que o fluxo de discovery já esteja em uso). Igual à revisão de código,
não existe aprovação automática por omissão: sem agente configurado, `spec/run`
cai num esqueleto heurístico e `spec/review` só reprova (nunca aprova sozinha).

Dois dos nove eixos do §6 são checados **antes de qualquer agente**: campo vazio é
fato, não opinião — `estrategia_de_testes` ou `plano_de_rollback` ausentes reprovam
na hora, sem gastar um agente revisor. O ciclo reprovado → nova versão → nova
revisão tem limite:

- `ASO_MAX_RODADAS_DOC` (default `3`) é o número de rodadas de revisão documental
  antes de uma reprovação virar `necessita_humano` — atravessa regenerações da
  mesma especificação (não reinicia a cada nova versão), evitando dois agentes
  (autor/revisor) discordando indefinidamente e queimando tokens sem fim. Esgotado,
  só `POST .../spec/approve` (papel `admin`) decide.

Especificação aprovada (`aprovado`/`aprovado_com_observacoes`) materializa os
`itens_de_trabalho` como cards, com dependências resolvidas por título.
`GET .../spec/history` e `GET .../discovery/history` trazem o histórico completo
(ring de até 5 versões) — reexecutar depois de uma reprovação **acrescenta** uma
versão nova, não substitui a anterior.

### Bateria de validações (§12 do fluxo.md, ADR-0022)

`validation_command` (um comando único) continua funcionando — inclusive na CI da
PR (`run_pr_ci`) — mas F5/F6 preferem uma **bateria nomeada**:
`PUT /v1/orchestrations/{id}/validation-checks` com uma lista de
`{nome, comando, categoria, bloqueante}`. Cada `comando` passa pelo mesmo guard do
legado (`validate_gate_command` — recusa `npm run dev`, `400`). O gate roda **um
`Criterion` por verificação**, todos até o fim (sem parar na primeira falha) —
diferente do comando único, que só dizia "falhou", a bateria diz **qual**
verificação falhou. Uma verificação `bloqueante: false` vira aviso, não reprovação.
`GET .../validation-checks/suggest` inspeciona o workspace
(`pyproject.toml`/`package.json`/`go.mod`/`Cargo.toml`) e sugere uma bateria sem
gravar nada — o operador aceita com `PUT`.

Sem bateria configurada, `checks_efetivos` converte o `validation_command` legado
numa única verificação `"testes"` — nenhuma orquestração anterior a este
incremento muda de comportamento.

### Roteamento de falha (§13 do fluxo.md, ADR-0019/0022)

Toda falha de execução passa por diagnóstico + política antes de decidir o que fazer —
não é mais "reexecuta 2x com a mesma configuração e desiste". `POST .../cards/{id}/run`
já tenta de novo internamente quando a decisão é `mesmo_agente`/`aumentar_effort`/
`trocar_executor`; só `bloquear` (`Blocked`) ou `escalar_humano` (`Failed`) encerram sem
sucesso. `GET .../cards/{id}/failures` traz o histórico (comando, mensagem, executor,
effort, `check`/`categoria` quando a falha veio da bateria, timestamp — até 5
tentativas); `POST .../cards/{id}/route` aciona o roteamento de novo manualmente,
depois que o operador corrigir a causa.

Desde a ADR-0022, uma verificação nomeada que falha dá `categoria` ao diagnóstico —
fato, não heurística por palavra-chave: `formatacao`/`lint` → `falha_trivial`
(nunca sobe effort, repete o mesmo agente com a saída no prompt);
`seguranca`/`dependencias` → `risco_alto` (escala para humano já na primeira
falha). A escalada (effort maior/outro executor) por reprovação de gate é gravada
por FASE (`agent_assignments[fase]`), não por card isolado — todos os cards da
mesma fase compartilham a bateria, então a próxima tentativa de qualquer um deles
já nasce com o degrau novo.

- `ASO_MAX_ESCALONAMENTOS` (default `3`) é o limite duro de tentativas automáticas por
  card antes de forçar `escalar_humano` — nunca deixa o laço de retry aberto para
  sempre, mesmo que a política ainda tivesse um passo de retry disponível.

### Escolha automática de esforço (§9 do fluxo.md, ADR-0022)

`DemandBrief.complexidade` (produzida pela triagem desde a ADR-0016) e o risco da
demanda decidem o esforço quando nenhuma escolha humana o define: penúltimo degrau
da resolução, logo antes do default do perfil do executor
(`explícito → etapa → orquestração → sugestão automática → perfil`). Cada
resolução automática gera um evento `EffortSugerido` no timeline (complexidade,
risco, fase, effort escolhido) — auditável, nunca silencioso.

- `ASO_EFFORT_AUTOMATICO` (default `1`, ligado) desliga a automação com `0`,
  restaurando o comportamento anterior (effort sempre cai no default do perfil
  quando não há escolha humana). A sugestão só age quando a orquestração de fato
  triou a demanda (`demand_brief` não vazio) — nunca muda o comportamento de uma
  orquestração que nunca chamou `/brief`.

### Implantação governada (§18-22 do fluxo.md, ADR-0023)

**Não confundir com [`docs/deploy.md`](deploy.md)**, que documenta como implantar
o ASO Runtime em si (a imagem Docker da API). Isto aqui é sobre o runtime
rastrear/governar implantações **dos projetos que ele orquestra**.

O MVP exclui deploy automático em produção e provisionamento cloud automático
(`requerimentos.md`) — por isso o runtime não provisiona infraestrutura nenhuma:
`PUT /v1/orchestrations/{id}/deploy/config` configura um comando de implantação
(mesmo `validate_gate_command` que recusa comando contínuo, `400`), um ambiente
(texto livre, não um pipeline de estágios), verificações pós-implantação (§20,
reaproveita `ValidationCheck` da bateria) e um comando de rollback opcional.
`POST .../deploy/run` exige o comando configurado e o **último quality gate**
com `status: PASSED` (§18: "testes aprovados") — sempre executa o comando; a
decisão humana é sobre ACEITAR o resultado, não sobre autorizar a tentativa
(mesmo raciocínio do discovery, ADR-0020). Implantação que falha vai direto a
`reprovado`; que sucede aplica risco alto/crítico, impacto sensível ou validação
reprovada → aguardando aprovação humana (`POST .../deploy/approve`, admin);
senão, aceite automático. `POST .../deploy/rollback` (admin) marca a
implantação como revertida e **sempre** abre um `KanbanCard` do tipo `Incident`
em `Backlog` — a tarefa de análise de causa raiz do §21.

O gate de F6 ganha o critério `deploy_aprovado` **só quando alguma implantação
já rodou** (`GET .../deploy` diferente de `"pendente"`) — orquestrações que
nunca chamam `/deploy/run` (a maioria) não mudam de comportamento, mesma regra
de não-regressão do `discovery_aprovado`/F1 (ADR-0020).

As colunas Kanban `Deploying`/`Validating` **continuam sem automação de
transição** — a governança de implantação opera no nível da orquestração, não
do card; ver [`docs/kanban.md`](kanban.md).

### Corrida de candidatos: BrokenPipeError corrigido (ADR-0024)

Até 2026-07-31, `POST .../cards/{id}/race` podia perder um candidato de forma
intermitente — mais visível sob carga (suíte de testes completa, ~2 de 5
execuções). A causa era `CliAgentExecutionProvider._rodar` escrever a tarefa
no stdin do processo **depois** de já ter iniciado as threads leitoras: um
comando que não lê stdin (ou já terminou) fecha o pipe antes da escrita, e
`BrokenPipeError` era tratado como falha do executor. Corrigido — o mesmo
padrão que `subprocess.communicate()` da stdlib usa: a escrita ignora
`BrokenPipeError`, e quem decide sucesso/falha volta a ser o `returncode`
real do processo. Detalhe completo, incluindo como foi reproduzido antes de
corrigir, em [ADR-0024](adrs/ADR-0024-corrida-de-candidatos-broken-pipe.md).

Independente da causa, uma corrida que perde candidato nunca fica silenciosa:
a resposta de `POST .../race` traz `falhas: [{executor, erro}]` além de
`candidates`, um evento `CandidateFailed` é registrado por candidato perdido,
e `next_step` cobra `corrida_degradada` (severidade `acao_do_operador`)
enquanto o card ainda não chegou a `Done`.

### QA manual (§16/§17 do fluxo.md, ADR-0025)

`POST .../cards/{id}/qa` registra uma verificação manual — cenário, passos
para reproduzir, ambiente, resultado esperado/obtido, evidências, gravidade.
`exige_qa_manual` (`control/qa.py`) decide quando o `next_step` cobra isso
antes de seguir: domínio `frontend`, complexidade `complexa`/`estrategica`,
ou card `Epic`/`Feature`. Fora dessa regra, QA continua opcional — registrável
a qualquer momento.

`POST .../cards/{id}/qa/{i}/fail` reprova a verificação: cria um card `Bug`
vinculado por `dependencies` (e `parent_id` quando a hierarquia — abaixo —
permitir), monta a descrição a partir dos passos/resultado/evidências, e
registra a falha no **mesmo** roteamento de falha do card original
(`control/failure.py`, diagnóstico `falha_de_qa`, política `mesmo_agente →
aumentar_effort → escalar_humano`) — nenhuma taxonomia nova. O card volta
para `NeedsFix` ou `Failed`, conforme a mesma política já decide para
qualquer outra falha de execução.

### Hierarquia épico → história → subtarefa (§7 do fluxo.md, ADR-0025)

`KanbanCard.parent_id` — nulo continua válido para todo card existente.
Produzida por `SpecWorkItem.itens_filhos` (spec aprovada — só um nível) e por
`BacklogItem.type` (backlog do LLM — sem árvore). Três regras aplicadas na
criação/movimentação, não só decorativas: profundidade máxima 3 (Epic →
Feature → Task), ciclo é erro, e um card com filho ainda aberto não chega a
`Done`. Cancelar um card cancela os filhos ainda abertos em cascata.

### Aprendizado da esteira (§24 do fluxo.md, ADR-0025)

`GET /v1/orchestrations/{id}/learning` (uma demanda) e `GET /v1/learning`
(consolidado entre todas) agregam por executor: execuções, falhas,
retrabalho, tempo médio, rodadas de revisão, erros recorrentes por categoria
— a partir do que já estava persistido (`card.failures`, `card.executor`,
`pr.review_rounds`, o event log). **Informativo**: o relatório não altera
nenhuma decisão automaticamente. Por isso a escolha de agente/modelo (§9 do
fluxo.md) continua declarada como decisão manual, não pendência — sem este
dado, automatizar seria adivinhar.

### Permissão de escrita do agente CLI (causa nº 1 de "diff vazio")

Em modo não-interativo, os CLIs **não escrevem arquivos por padrão** — não têm como pedir
aprovação, então respondem em texto, saem com código 0 e deixam o worktree intacto. O ASO
detecta o diff vazio; se a mensagem também mencionar permissão/sandbox, o diagnóstico é
`sem_permissao` e o card vai direto para `Blocked` sem re-tentar (nenhum aumento de effort
resolve permissão) — senão, tenta de novo com o mesmo agente antes de escalar. O comando
do executor precisa conceder a permissão explicitamente:

| Agente | Comando mínimo que escreve |
|---|---|
| Claude Code | `claude -p --permission-mode acceptEdits` (edita arquivos) |
| Claude Code | `claude -p --dangerously-skip-permissions` (edita **e** roda comandos) |
| Codex | `codex exec --sandbox workspace-write` (já embutido nos perfis gerenciados) |

Com `acceptEdits` o agente altera arquivos mas **não executa comandos** — cards que precisem
rodar build/testes travam nesse ponto. Conceder autonomia total é defensável aqui porque a
contenção do ASO é o **worktree isolado** + diff coletado + merge governado com CI e revisão
(regra 5 · [ADR-0009](adrs/ADR-0009-entrega-de-codigo-governada.md)), não a permissão do CLI.

Para corrigir um catálogo já existente: [`scripts/fix-executor-permissions.sh`](../scripts/fix-executor-permissions.sh)
(aceita `ASO_CLAUDE_PERMISSION_FLAG` para escolher a flag). Quando o card falha assim, o
motivo registrado passa a incluir **a última fala do agente** e o "Próximo passo" mostra o
bloqueio `executor_sem_permissao` com a orientação.

### Ver o que o agente está fazendo (streaming)

A tela de detalhe tem um painel "O que o agente está fazendo" que preenche em tempo real
([ADR-0015](adrs/ADR-0015-observabilidade-ao-vivo-da-execucao.md)). O ASO lê os pipes do
agente linha a linha, mas **a riqueza do que aparece depende do CLI**: em modo
não-interativo, `claude -p` imprime apenas a resposta final. Para ver ferramenta por
ferramenta, o CLI precisa emitir NDJSON:

| Agente | Flag que produz narração |
|---|---|
| Claude Code | `--output-format stream-json --verbose` |
| Codex | `--json` |

```bash
./scripts/enable-agent-stream.sh        # acrescenta as flags ao catálogo (idempotente)
./scripts/enable-agent-stream.sh --off  # remove
./scripts/manager.sh reiniciar          # necessário: o catálogo é lido no boot
```

O script usa a API quando ela está no ar e edita `.aso/executors.json` quando não está.
Sem as flags nada quebra — o painel cai no modo bruto e mostra as linhas como vierem.

Limites a conhecer:

- O log fica **em memória**: 2 000 linhas por orquestração, e **não sobrevive a restart da
  API**. É telemetria de acompanhamento; o que precisa durar (falha, motivo, diff) fica no
  event log e no `block_reason` do card.
- `ASO_AGENT_TIMEOUT` (default `1800`, em segundos) encerra um agente travado. Antes não
  havia limite nenhum: um CLI parado esperando permissão prendia uma thread do servidor e
  um worktree para sempre.
- Sem TTY, alguns CLIs bufferizam a saída em blocos de 4-8 KB por decisão própria. O NDJSON
  resolve isso para Claude e Codex; para outros agentes o "ao vivo" pode sair em rajadas.

### Catálogo Codex compatível com a conta

`./scripts/manager.sh seed` consulta `codex app-server`/`model/list` pelo processo da API e
sincroniza somente os modelos disponíveis na autenticação atual. O perfil `codex-default`
não fixa `-m` e ignora apenas o `config.toml` pessoal, evitando que ele force um modelo
incompatível; a autenticação ChatGPT é preservada. Perfis personalizados e Claude não são
alterados. Use `ASO_CODEX_BIN` quando o binário correto não for o primeiro `codex` do `PATH`.

O ASO recusa perfis indisponíveis antes de criar worktree. Também recusa servidores e
watchers (`npm run dev`, `--watch`) como quality gate: configure um comando finito, como
`npm test` ou `npm run build`. Em uma orquestração `created`/`blocked`, corrija pelo detalhe
ou por `PATCH /v1/orchestrations/{id}/execution-settings` e repita somente o docs-first.
Se uma tentativa anterior deixou apenas o scaffold de segurança, o retry reconhece que o
workspace ainda não tem código e completa o template determinístico, sem pedir ao agente que
invente fatos nem tratar o diff vazio como perda da orquestração.

## Custo real e orçamento (ADR-0026)

- O envelope final do CLI (`type: "result"` no Claude Code) traz
  `usage`/`total_cost_usd`; o runtime captura e acumula em `card.uso`, `card.closure`
  (§23) e no relatório de aprendizado (`GET .../learning`). Um executor que não
  informa uso aparece como `execucoes_sem_custo`, nunca como custo zero.
- `ASO_ORCAMENTO_PADRAO_USD` define o teto de gasto (US$) de orquestrações **novas**.
  Sem a variável, `orcamento_usd` fica `None` — sem teto, comportamento idêntico ao
  runtime antes desta ADR. `PUT /v1/orchestrations/{id}/budget` (`{teto_usd}`, admin)
  eleva ou remove o teto de uma orquestração existente a qualquer momento.
- Com teto configurado, `GET .../next-step` mostra `orcamento_em_alerta` (≥ 80%,
  informativo) e `orcamento_estourado` (≥ 100%, bloqueia). Estourado: `POST
  .../cards/{id}/run` e `.../race` passam a recusar (`409`) — nunca mata uma
  execução em curso, só recusa iniciar uma nova. O roteamento de falha (ADR-0019)
  também consulta o teto antes de `aumentar_effort`/`trocar_executor`: estourado vira
  `escalar_humano` com motivo de orçamento.
- Nunca compare custo bruto entre executores no relatório — use
  `custo_por_entrega` (`GET .../learning`), que divide pelo que de fato chegou a
  `Done`.

## Cards órfãos e worktrees órfãos após crash (ADR-0027)

Se a API cair no meio de uma execução (`Ctrl-C`, OOM, deploy), dois sinais aparecem
depois que ela sobe de novo:

- **Card preso em `InProgress`**: `GET .../next-step` mostra `card_orfao` quando
  `updated_at` do card está parado há mais que `ASO_AGENT_TIMEOUT` (default 1800s) —
  o mesmo timeout que já mataria um agente travado garante que nenhum processo vivo
  pode ainda estar nele. A ação do bloqueio chama `POST .../cards/{id}/route`
  (roteamento de falha padrão, ADR-0019) — não há passo manual diferente disso.
- **Worktree órfão**: `GET .../orchestrations/{id}/worktrees` lista tudo que existe
  em `.aso/worktrees/` do repositório, com `orfao: true/false` (órfão = nenhum card
  ativo referencia por branch). `POST .../worktrees/prune` (admin) remove só os
  órfãos via `git worktree remove` + `git worktree prune` — **nunca apaga o banco**,
  diferente de `./scripts/reset.sh` (que continua sendo o recurso para "zerar tudo").

## Observabilidade

- Eventos de domínio no `EventLog`: `OrchestrationCreated`, `ContextPatchApplied`,
  `QualityGateEvaluated`, `SnapshotCreated`, `ConflictRaised`, `CardMoved`, `AgentRun*`.
- Timeline por orquestração: `GET /v1/orchestrations/{id}/timeline` ou `aso timeline <id>`.
- **Métricas Prometheus** em `GET /metrics` (formato de exposição text/plain): `aso_orchestrations_total`,
  `aso_cards{status=...}`, `aso_open_conflicts_total`, `aso_adrs_total`, `aso_snapshots_total`.
- Auditoria: `GET /v1/orchestrations/{id}/audit` (eventos + patches aplicados/rejeitados + conflitos + approvals).

## Incidentes (básico)

1. Identificar a orquestração afetada (timeline, logs).
2. Verificar conflitos abertos e cards em `Blocked`/`Failed`.
3. Se estado inconsistente: restaurar o último snapshot estável (SnapshotEngine) e registrar ADR de rollback.
4. Registrar postmortem e converter em card de melhoria/tech-debt.
