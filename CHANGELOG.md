# Changelog — ASO Runtime

Formato baseado em Keep a Changelog. Versionamento semântico.

## [0.1.0] — não lançado (MVP-1 + persistência)

### Planejamento
- **Diagnóstico de fidelidade ao `fluxo.md` e ao `wiframe-fluxo.md`:** o runtime está
  em ≈55% de aderência — funcionalidade da esteira em 85%, modelo de dados em 78%, mas
  cobertura de telas em 42%, navegação em 15% e estilo visual em 25% (a spec pede
  wireframe claro; a UI é um console escuro sem sidebar). Registrado em
  [docs/plano-fidelidade-fluxo.md](docs/plano-fidelidade-fluxo.md) com 27 cards
  (FID-01…FID-27) no Backlog do board, sob os épicos EPIC-9 (lacunas da esteira) e
  EPIC-10 (shell e telas).

### Corrigido
- **6 bugs reais do `/code-review ultra` pós-FID-27 (ADR-0055):** com o
  backlog de fidelidade 100% `Done`, uma revisão multiagente sobre o diff
  acumulado (FID-22–FID-27, ainda não commitado) encontrou 6 defeitos reais.
  Decisão do usuário (opção recomendada): corrigir os 6, não só os mais
  críticos. **(1)** `card.tentativa_atual` soma sucesso e falha, mas era
  passado direto a `decidir()` como contador de escalação — 2 sucessos + 1
  falha real escalava para humano já na 1ª falha, pulando `mesmo_agente`/
  `aumentar_effort`; novo campo `tentativa_falha_atual` (uncapped, zera a
  cada sucesso) corrige, com migration validada no Postgres real. **(2)** a
  Tela 03 (`demand_brief` completo) não propagava `decision_input` ao
  planejador — a classificação preenchida à mão nunca influenciava a escolha
  de agente/regra de roteamento; corrigido reaproveitando
  `DemandBrief.to_decision_input()`. **(3)** revisão reprovada com PR cujo
  único comentário era de rodada ANTERIOR já resolvida descartava
  `verdito.acoes`, deixando `NeedsFix` sem orientação nenhuma — o fallback
  agora olha o resultado filtrado, não a existência histórica de
  comentários. **(4)** `saude_pos_deploy` ignorava `deploy.status` — um
  comando de deploy que falha (validação nunca roda) era relatado como
  saudável, sugerindo `concluir_implantacao`; `STATUS_FALHOU` agora checa
  primeiro. **(5)** `_faixa` (painel de recomendação, Tela 13) colapsava
  todo grupo de custo/tempo empatado no rank mais baixo (`list.index` sempre
  acha a 1ª ocorrência) — corrigido com rank médio do grupo; e
  `get_learning_report_global()` hidratava o sistema inteiro num endpoint
  só-leitura chamado a cada edição de classificação — agora recorta por
  `project_id`. **(6)** `PUT /v1/agent-definitions/{id}` podia revogar
  `ferramentas`/`permissoes` reais de um papel por omissão de campo (default
  Pydantic `[]`, `AgentCatalogService.update` substituindo em vez de
  mesclar) — fonte de verdade real das permissões (`AgentRegistry.seed_from_catalog`,
  ADR-0053); a UI existente não explorava isso (sempre envia o objeto
  completo), mas violava deny-by-default como contrato de API. Corrigido com
  semântica PATCH-like: campo omitido/`null` preserva o valor atual, só
  lista explícita substitui. Os 6 achados têm teste de regressão dedicado,
  verificado falhando antes da correção. Bateria completa verde (1356
  testes, 93.42% de cobertura); migration validada no Postgres real
  (`docker compose up` + `./scripts/smoke.sh`).
- **Painel de atividade mostrava o começo da história (ADR-0015):** ele pedia
  `timeline?page_size=14`, e `events_page` ordena `seq ASC` com `offset=0` — recebia os 14
  eventos **mais antigos** da orquestração e os invertia no render, recarregando a mesma
  fatia errada a cada tick do SSE. `events_page`/`timeline_page` ganharam `newest_first`,
  aplicado na consulta ao banco (reordenar depois só embaralha a fatia errada).
- **Agente CLI sem tempo limite (ADR-0015):** era o único subprocess do repositório sem
  timeout — um `claude -p` travado esperando permissão interativa prendia uma thread do
  servidor e um worktree para sempre. Agora `ASO_AGENT_TIMEOUT` (default 1800 s) encerra o
  processo e reporta a cauda da saída. `artifacts["stdout"]` passou a guardar os **últimos**
  4 000 caracteres em vez dos primeiros 2 000, e `stderr`, antes descartado no caminho de
  sucesso, agora entra no log.
- **Estado de runtime versionado por engano:** `aso.db` (356 KB, SQLite binário) estava
  rastreado desde o commit inicial e acumulava 6 commits de churn — ele é criado pelo
  fallback `sqlite:///aso.db` de `migrations/env.py` sempre que se roda `alembic` sem
  `ASO_DATABASE_URL`, e o que guardava era uma orquestração de teste esquecida. Saiu do
  índice (`git rm --cached`) e entrou no `.gitignore`, junto de `*.sqlite`/`*.sqlite3` e de
  `.aso/worktrees/` — esta última já era injetada pelo runtime no `.gitignore` dos
  repositórios-alvo (`WorkspaceService.ensure_git`), mas faltava no próprio ASO, que
  também já foi alvo de orquestração. A governança versionada (`.aso/context`,
  `.aso/kanban`, `.aso/quality-gates`, `.aso/snapshots`, `.aso/reviews`) segue rastreada
  de propósito.
- **O agente executava cego (ADR-0014):** `_build_task` mandava só o `user_request` da
  orquestração inteira e um `card_id` opaco — o título, a descrição e os critérios de
  aceite do card nunca saíam do board. Agora vão na tarefa e no prompt do wrapper, junto
  da convenção de commit sugerida.
- **Coleta de diff descartava o trabalho de agentes que commitam:** `collect_diff`
  comparava apenas o índice (`git add -A` + `git diff --cached`), então quando o agente CLI
  commitava o que produziu — comportamento que o próprio wrapper do ASO pede ("commits
  pequenos") — a árvore ficava limpa, o diff saía vazio e o card era marcado como `Failed`,
  **descartando código real**. Agora o diff é coletado contra o **merge-base com o HEAD do
  repo base**: cobre commits do agente e mudanças pendentes, e ignora o que o repo base
  ganhou em paralelo. `commit()` virou no-op quando a árvore já está limpa (o trabalho já
  está nos commits do agente).
- **Diagnóstico de agente CLI sem permissão de escrita:** em modo não-interativo,
  `claude -p` (sem `--permission-mode`) e `codex exec` em sandbox read-only respondem em
  texto, saem com código 0 e deixam o worktree intacto — o card falhava com "diff vazio" e
  a saída do agente era descartada, sem pista da causa. Agora o motivo registrado no card
  inclui **a última fala do agente**, o "Próximo passo" mostra o bloqueio dedicado
  `executor_sem_permissao` com as flags necessárias, os perfis Codex gerenciados passam a
  ser criados com `--sandbox workspace-write` (o `--ignore-user-config` descartava o
  sandbox do `config.toml` pessoal) e `scripts/fix-executor-permissions.sh` corrige um
  catálogo já existente. Documentado em `docs/operations.md` e no README.

### Corrigido
- **Corrida de candidatos perdia candidato de forma intermitente (ADR-0024):**
  `CliAgentExecutionProvider._rodar` escrevia a tarefa no stdin do processo
  depois de já iniciar as threads leitoras — um comando que não lê stdin (ou
  já terminou) fecha o pipe antes da escrita, e `BrokenPipeError` era tratado
  como falha do executor sem sequer checar o `returncode` real. Reproduzido
  com um teste de estresse (`tests/integration/test_race_stress.py`, N
  repetições) antes de corrigir — reprovava logo na 1ª rodada. Corrigido com
  o mesmo padrão que `subprocess.communicate()` da stdlib usa para o mesmo
  motivo: ignora `BrokenPipeError` na escrita, deixa o `returncode` decidir.
  Independente da causa, o runtime parou de engolir candidato perdido:
  `compare()` devolve `falhas`, evento `CandidateFailed` por candidato, e
  `next_step` cobra `corrida_degradada` enquanto o card não chegou a `Done`.
  Suíte completa rodada 5× seguidas após a correção: 781 passed em todas.

### Adicionado
- **Requisitos de UX obrigatórios aplicados transversalmente (ADR-0054,
  FID-27) — card de encerramento da missão de fidelidade:** wf §39 lista 12
  requisitos que toda tela do runtime deveria cumprir; a `description` do
  card no board resumia só 10, omitindo "toda tela informa status atual" e
  "cada alteração gera nova entrada de auditoria". Decisão do usuário
  (opção recomendada): tratar os **12** pontos literais do wireframe como
  escopo real — os 2 omitidos já saíram cobertos sem exigir mudança. Uma
  varredura (Explore) contra as ~20 páginas reais entregues por FID-10 a
  FID-26 encontrou **9 lacunas**, todas fechadas, nenhuma exigindo
  migration (os dados já existiam no backend). **`aprovacoes.html`** (a
  inbox central) violava dois requisitos na mesma tela — Aprovar/Rejeitar
  disparavam sem confirmação e sem mostrar critérios; decisão do usuário
  (opção recomendada): fechar com `confirm()` nativo (mesmo padrão já usado
  em 5 outras páginas), com o texto do diálogo compondo um resumo de
  `action`/`tipo`/`risk`/`reason`/`payload` — não existe campo
  `criterios`/`checklist` pronto no backend para esse tipo de aprovação. A
  coluna "Origem" da mesma tabela ganhou pill automática/manual, corrigindo
  uma inconsistência com a coluna Risco ao lado (que já tinha pill).
  **`execucoes.html`** ganhou a coluna **Modelo** que faltava na tabela
  agregada (`card.executor` já existia, só não era exibido).
  **`auditoria.html`** — "Card: X · Demanda: Y" era texto puro, sem
  navegação de volta; ganhou `<a href>` para `/ui/card-detalhe` e
  `/ui/demanda-detalhe`. **`demanda-detalhe.html`/`card-detalhe.html`** — o
  campo de risco era texto plano, inconsistente com `demandas.html`/
  `aprovacoes.html`; nova `pillRisco()` replicando o `TOM_RISCO` de
  `demandas.html` (ADR-0038). **`card-detalhe.html`** — a timeline genérica
  não marcava retrocessos visualmente; nova `ehRetornoDeFluxo()`, heurística
  documentada no código (não existe campo booleano de "retorno" no
  `CardEvent`, então é inferido, nunca fabricado); a aba Falhas passou a
  reexibir o `next_action` que já existia no evento, mas só aparecia na aba
  Histórico. **`demanda-detalhe.html`** — a aba Histórico (consome
  `/timeline`, eventos de **domínio**, um stream estruturalmente diferente
  do `CardEvent` do card) descartava o `payload` inteiro de cada evento,
  mostrando só tipo+data; passou a exibir o `payload` por completo, sem
  fabricar campos que esse tipo de evento não tem. Novo teste
  `tests/integration/test_ux_transversal_wf39.py` (8 testes) — primeiro
  gate automatizado cross-página da missão, travando as 8 correções contra
  regressão futura. **Com este card, os 137 cards do board (`FID-01`…`FID-27`
  + `TASK-01`…`TASK-110`) estão 100% `Done`** — suíte completa com cobertura
  ≥80% (1345 testes, 93,29%).
- **Catálogo de agentes como fonte de verdade de permissões (ADR-0053,
  FID-26):** a Tela 30 pedia 13 campos por agente e 14 agentes-exemplo, mas
  as duas estruturas pré-existentes não cobriam isso — `AgentRegistry`
  (16 papéis hardcoded, alimenta a `PermissionPolicy` real do `ContextBus`)
  não é persistente nem editável em runtime, e `ExecutorCatalog` é um
  conceito totalmente diferente (modelos, não papéis/permissões). Decisão
  do usuário, **opção não recomendada** (escolhida deliberadamente sobre
  "espelho somente leitura"): o catálogo novo — `AgentDefinition` /
  `AgentDefinitionRepository` / `AgentCatalogService` (mesmo template de
  `RoutingRuleRepository`/`RoutingRuleService`, ADR-0028) — é a **fonte de
  verdade real** das permissões. `AgentRegistry.seed_from_catalog()`
  substitui `seed_defaults()` na construção do registry: semeia a base
  segura primeiro, depois sobrescreve `allowed_tools`/`context_sections` de
  um papel real com `ferramentas`/`permissoes` da definição ativa vinculada
  a ele — editar uma definição no catálogo muda de fato o que aquele agente
  pode escrever via `ContextBus` na próxima orquestração. Não-destrutividade
  do primeiro boot **confirmada por comparação direta**: catálogo vazio e
  catálogo com os 14 exemplos (ferramentas/permissões copiadas verbatim dos
  valores hardcoded) produzem `permission_map()` byte-idêntico ao baseline
  pré-ADR. **Bug real encontrado e corrigido** durante a implementação: nada
  impedia duas definições ativas com o mesmo `role`, causando "última values
  ganha" silenciosa na ordem alfabética de `seed_from_catalog` — corrigido
  com `_verificar_role_unico` (recusa criar/ativar uma segunda definição
  para um papel já ocupado; desativar libera o papel). **14 agentes-exemplo
  pré-provisionados**, decisão do usuário (opção recomendada): **11/14**
  mapeados para papéis reais do `AgentRegistry` (Orquestrador, Arquiteto,
  Analista de requisitos, Desenvolvedor backend/frontend, Especialista em
  banco/infraestrutura, QA, Code reviewer, Segurança, Documentação); **3/14**
  (Discovery técnico, Deploy, Incidentes) ficam **sem papel, honestamente**
  — nenhum papel dedicado existe hoje no `AgentRegistry` para eles. **Limite
  de custo e de tentativas por agente**: novo terceiro freio independente e
  aditivo (`_recusar_se_limite_do_agente_estourado`, chamado em `run_card`),
  convive com o orçamento por orquestração (ADR-0026) e o limite por card
  (ADR-0031), cada um em escopo diferente. Migration `54e2ef2b7e2f` (tabela
  global `agent_definitions`, mesmo precedente de `routing_rules`). Escrita
  em `/v1/agent-definitions` exige papel `admin` — nível crítico máximo,
  já que controla permissão real do `ContextBus`. `/ui/agentes` deixou de
  ser placeholder: editor modal com os 13 campos, mesmo padrão de
  `/ui/regras-roteamento`. Validado ao vivo em Docker/Postgres real: os 14
  exemplos apareceram, CRUD completo funcionou, criação de segunda definição
  para papel já vinculado devolveu 400, e uma edição restringindo
  ferramentas/permissões de "Desenvolvedor backend" sobreviveu a um restart
  do container `api`. 34 testes novos (`test_agent_catalog.py`,
  `test_agent_catalog_api.py`, `test_agent_catalog_persistence.py`,
  `test_agent_catalog_html.py`); `ruff`/`mypy --strict`/`alembic check`
  limpos; suíte completa com cobertura ≥80% (1337 testes, 93,29%).
- **Métricas e aprendizado com recorte por projeto e período (ADR-0052,
  FID-25):** a maior parte da Tela 29 já tinha fonte real —
  `observability/aprendizado.py` (ADR-0025) já agregava por executor/modelo
  (execuções, falhas, retrabalho, tempo médio, custo) e `list_orchestrations`
  (ADR-0038) já filtrava por projeto/período em SQL real indexado, então a
  tabela de comparação de modelos (wf §31.2) não precisou de nenhuma mudança
  de backend. O card cita `aprendizado.py` como origem das 8 recomendações
  automáticas (wf §31.3), mas o módulo produzia só **1** frase de texto
  livre (um único heurístico) — nenhuma das 8 categorias existia como
  lógica distinta. Nova `recomendacoes_estruturadas()`: **6 categorias com
  regra determinística e limiar fixo documentado** (aumentar effort para
  categoria de falha recorrente; evitar modelo com ≥50% de taxa de falha;
  adicionar teste automático quando a falha recorrente é de categoria
  "testes"/"qa"; modificar critérios de aprovação quando a taxa de
  aprovação é <50%; alterar limite de tentativas quando intervenções
  humanas atingem ≥30% dos cards; ajustar regras de roteamento quando o
  retrabalho atinge ≥30% dos cards). **"Criar novo agente especializado"**
  e **"criar template de card"** ficam **permanentemente desabilitadas** —
  nenhum sinal nos dados distingue os cenários que as justificariam, mesmo
  padrão de "criar investigação separada" desabilitada no FID-21/ADR-0048.
  **"Cobertura de testes"** (indicador 14 dos 15) é **sempre** `None`,
  nunca calculado — o runtime não tem número de cobertura chegando ao
  domínio (só a categoria de falha "testes", uma correlação fraca que
  mentiria se usada como proxy); mostrado honestamente como "não
  disponível". `get_learning_report_global` ganhou
  `project_id`/`data_de`/`data_ate` — filtro SQL real e indexado de
  `list_orchestrations` aplicado **antes** de hidratar qualquer
  orquestração, restringindo a lista primeiro (mesmo cuidado de escala de
  `audit_page`, ADR-0051, que rejeitou explicitamente hidratar o sistema
  inteiro em Python). **4 indicadores novos** (tempo/custo médio por
  demanda, número médio de tentativas, falhas por agente): `consolidar()`
  ganhou parâmetros de **contagem bruta**, somados pelo coletor antes de
  qualquer divisão — nunca uma média-de-médias, matematicamente errada
  entre orquestrações de tamanhos diferentes; "primeiro ciclo"/"número
  médio de tentativas" usam `card.tentativa_atual` (contador autoritativo
  e sem limite de ring, ADR-0031), nunca o ring de tentativas (capado em
  10); "falhas por agente" usa um campo novo `CardSnapshot.agente`
  (`card.assignee`, o PAPEL) — agrupamento deliberadamente diferente de
  `desempenho_por_executor` (agrupado por `card.executor`, o MODELO), já
  que o wireframe pede os dois como indicadores distintos. `/ui/metricas`
  deixou de ser placeholder: página única cross-demanda (mesmo padrão de
  `/ui/auditoria`, FID-24, já que a Tela 29 também é naturalmente global)
  com os 15 indicadores, a tabela de comparação de modelos e as 8
  recomendações com justificativa quando disparadas. Nenhuma migration
  necessária — tudo vive em dataclasses puras computadas na leitura.
- **Auditoria cross-demanda com filtros (ADR-0051, FID-24):** a aba "audit"
  do console legado só mostrava contadores agregados — zero filtro sobre
  registros individuais. Investigação prévia encontrou que nenhuma query
  cross-orquestração filtrável existia no runtime (só `/v1/activity`, um
  peek plano sem filtro) e que 5 dos 14 campos do wireframe (Projeto,
  Modelo, Effort, Etapa-como-Fase, Identificador da execução) não tinham
  fonte durável — só existiam nos rings limitados (`tentativas` capado em
  10, `failures` em 5), que violariam o critério "registro nunca
  sobrescrito" se reaproveitados como fonte. `CardEvent`/`CardEventRow` (já
  append-only e nunca truncado, ADR-0019) ganhou 4 campos novos opcionais
  (`model`, `effort`, `phase`, `execution_id`), preenchidos **daqui pra
  frente** nos pontos de escrita já existentes (`_apply_execution`/
  `_route_failure`, chamados de `run_card`/`run_plan`) — eventos antigos e
  movimentação manual ficam honestamente `None` nesses 4 campos, nunca
  fabricados retroativamente. `execution_id` é gerado uma vez por tentativa
  de execução e propagado a todo `CardEvent` nascido dela (confirmado:
  "AgentStarted"→"TestsPassed" da mesma execução compartilham o mesmo id).
  Nova consulta `audit_page` segue o padrão de query SQL real e paginada de
  `list_orchestrations` (ADR-0038) — deliberadamente **não** o padrão N+1 de
  `list_all_approvals` (hidratar toda orquestração em Python), rejeitado
  porque auditoria cresce sem limite; implementada nos dois adapters (SQL e
  in-memory), contrato `OrchestrationRepository` mantido simétrico. **6
  filtros reais** (wf §30.3): data/agente/etapa sobre colunas indexadas,
  projeto via `JOIN`, demanda por `orchestration_id`, resultado via `ILIKE`
  substring (texto livre, não um enum fabricado). **Exportação em CSV**
  (novo `GET /v1/audit/export`) — primeiro export CSV do projeto (o único
  precedente, `closure/export` da ADR-0050, é markdown, adequado a
  relatório narrativo, não tabela de auditoria); teto defensivo de 5000
  linhas, documentado explicitamente. `/ui/auditoria` deixou de ser
  placeholder: página única cross-demanda (a auditoria já é naturalmente
  global, não picker+drilldown) com os 6 filtros, lista paginada e
  exportação carregando os mesmos filtros aplicados. Uma migration nova (4
  colunas + 3 índices em `card_events`), validada em SQLite **e Postgres
  real via Docker**, incluindo sobrevivência a um restart completo do
  container da API.
- **Aprovação, implantação, validação, rollback, aceite e encerramento
  (ADR-0050, FID-23):** as Telas 22-27 (wf §24-§29) giram em torno de UM
  `DeployRun` da demanda (Telas 22-26) ou da demanda inteira (Tela 27), então
  a aba "Deploys" de `demanda-detalhe.html` ganhou o **pipeline visual de 5
  estágios** (Tela 23) — descoberto já **100% pronto no backend desde o
  FID-02** (`PIPELINE_PADRAO` já usava os mesmos 5 nomes do wireframe), só
  faltava a UI. Ganhou também o **checklist de aprovação de 9 itens +
  avaliação de risco** (Tela 22, wf §24): 4 itens com sinal real (PR
  aprovada, testes aprovados, plano de rollback disponível, aprovação
  humana realizada), 5 sem sinal — os mesmos já documentados como sem sinal
  desde a ADR-0023, nunca fabricados. **Saúde pós-implantação de 4 níveis +
  decisão sugerida** (Tela 24, wf §26): `saude_pos_deploy` deriva de FATO —
  `validacao_resultados` já distinguia item bloqueante de não-bloqueante
  (§20) desde a ADR-0023; "saudável com alertas" é só quando um item
  NÃO-bloqueante falhou, nunca heurística. A decisão sugerida é só uma
  **sugestão textual, nunca uma ação automática** — quem executa é sempre o
  endpoint real, acionado manualmente pelo operador. **Rollback com
  estratégia + checklist de 6 itens** (Tela 25, wf §27): novo campo
  `DeployRun.rollback_estrategia`, puramente descritivo — documentado
  explicitamente que o runtime sempre roda o mesmo
  `deploy_rollback_command` independente da estratégia escolhida, sem
  execução diferenciada real; do checklist, 4 itens têm sinal real
  (incluindo "abrir análise de causa raiz", que reaproveita o `Incident`
  que `rollback_deploy` já cria automaticamente, ADR-0032), 2 sem sinal.
  Aba "Incidentes" ganhou timeline completa e ações investigar/resolver.
  **3 sub-tipos de aceite humano** (Tela 26, wf §28.2): novo campo
  `DeployRun.tipo_aceite_humano` (produto/técnico/negócio), opcional, só
  populado quando o operador informa — nunca inferido. **Nova aba
  "Encerramento"** (14ª aba de `demanda-detalhe.html`) cobre a Tela 27 (wf
  §29): primeiro agregador no nível da DEMANDA inteira
  (`_build_demand_closure`) — mesma disciplina de `_build_card_closure`
  (ADR-0021, "só monta o que o runtime já tem à mão"), até então só existia
  por card. Discrepância real encontrada entre as specs e resolvida: a
  wireframe tem 14 blocos (inclui "Cards concluídos"), mas `fluxo.md` §23 e
  o próprio critério de aceite do card ("13 blocos") só têm 13 — resolvido
  honrando o texto literal do card: 13 blocos no relatório, "Cards
  concluídos" vira métrica de resumo (wf §29.2), não um 14º bloco. Novo
  `GET .../closure/export` devolve markdown pronto para download
  (`Content-Disposition: attachment`) — endpoint real no backend, não
  geração client-side. `/ui/implantacoes` deixou de ser placeholder e segue
  o padrão picker+drilldown de `/ui/execucoes`/`/ui/testes`/`/ui/code-reviews`
  (FID-21/22); `/ui/aprovacoes` quebra esse padrão deliberadamente e vira
  uma **inbox cross-demanda real** (`GET /v1/approvals?status=` já existia,
  cross-orquestração) — mais honesto que replicar o picker só por
  consistência visual. Nenhuma migration necessária — todos os campos
  novos vivem no ring JSONB `deploy_runs` já existente.
- **Code review, correção obrigatória, testes manuais e bug manual (ADR-0049, FID-22):**
  as Telas 18/19/20/21 (wf §20-§23) também são sobre **um card específico**
  — `card-detalhe.html` teve as abas "Review" e "Testes" expandidas, mesmo
  padrão de "expandir aba existente" do FID-18/FID-21. **Resumo do review**
  (wf §20.1) ganhou commits e linhas adicionadas/removidas via novos
  `WorktreeManager.commit_count`/`line_stats` (`git rev-list --count`/`git
  diff --shortstat`). **Checklist de 12 eixos** (wf §20.2) mostra os rótulos
  fixos do wireframe ao lado do `pontos_verificados` **real** (texto livre
  do revisor) — nunca cruzados um a um, para não fabricar uma precisão de
  auditoria que o dado não sustenta, mesma disciplina de "fato, não palpite"
  já usada na confiança de falha (ADR-0048) e de recomendação (ADR-0044).
  Comentários de review agora mostram os 8 campos do wf §20.3 (`ReviewComment`,
  ADR-0033, já tinha todos — só a UI cortava para 4). **Correção obrigatória
  travada de verdade no backend**: `run_review` recusa com `409` quando
  `card.status == NeedsFix` — o card precisa passar de volta por `Testing`
  antes de nova revisão, reaproveitando a máquina de estados já existente
  (ADR-0047), sem mecanismo novo. **Plano de teste manual** (wf §22.1):
  `QaCheck` ganhou `codigo` (gerado via `gen_id`, nunca um "QA-001"
  fabricado como no exemplo do wireframe)/`titulo`/`pre_condicoes`, sem
  migration (ring JSONB no card, como já era). **Registro de bug manual**
  (wf §23): nova entidade `BugReport`, tabela relacional própria
  (`bug_reports`) — mesmo padrão de `Incident` (ADR-0032), escolhido depois
  de comparar explicitamente contra o padrão JSONB do `Documento` (FID-19) e
  concluir que bug é "lista de tamanho variável com ciclo de vida próprio",
  não um ring versionado. `card_original_id` é o campo "Card original" do
  wf §23.1 (o card que tinha o problema); `card_id` é o `KanbanCard(type=Bug)`
  recém-criado, objeto rastreável no Kanban, mesmo papel de `Incident.card_id`.
  `create_bug_report` reaproveita a mesma forma de descrição textual de
  `_criar_bug_de_qa` (ADR-0025), sem duplicar lógica. Das 6 opções de
  "retorno de fluxo" (wf §23.2), só **"Criar card independente"** tem efeito
  real (bug nasce sem `dependencies`/`parent_id`); as outras 5 ("retornar
  para implementação/infraestrutura/banco de dados/documentação/
  arquitetura") são **metadado descritivo** — o runtime não tem roteamento
  automático entre disciplinas/times, fabricar isso mentiria sobre o que o
  sistema faz; a intenção do operador fica gravada e visível. `/ui/code-reviews`
  deixou de ser placeholder — lista agregada por demanda, mesmo padrão de
  `/ui/execucoes`/`/ui/testes` (FID-21). `/ui/testes?id=` ganhou tabela de
  bugs registrados, fechando o gap que o próprio FID-21 já documentava; as
  cores de status de QA foram corrigidas (o vocabulário real é
  `passou`/`falhou`/`pendente` — a UI antiga comparava com
  `aprovado`/`reprovado`, que nunca existiram como valor real). Uma
  migration nova (`bug_reports`), validada em SQLite **e Postgres real via
  Docker**, incluindo sobrevivência a um restart completo do container da
  API (prova que o dado veio do banco, não só do cache em memória).
- **Execução, quality gates e tratamento de falhas (ADR-0048, FID-21):**
  o conteúdo das Telas 15/16/17 é sobre **um card específico** em execução,
  não a demanda inteira — `card-detalhe.html` (FID-14/ADR-0041) ganhou uma
  11ª aba "Falhas" e as abas "Execuções"/"Testes" já existentes foram
  expandidas, mesmo padrão de "expandir aba existente" já usado no FID-18
  para Discovery. Dos 8 controles em voo do wf §17.2, **6 ganharam
  funcionalidade real**: Cancelar/Transferir agente/Marcar bloqueado
  reaproveitados como já estavam; **Aumentar effort/Trocar modelo** (dois
  métodos novos) reaproveitam **as mesmas funções puras** do roteamento
  automático de falha (`proximo_effort`/`proximo_executor`, ADR-0019) —
  zero lógica de decisão duplicada, só um caminho manual novo de acioná-las;
  `run_card` passou a considerar `card.effort_override`/`card.executor_override`
  com a mesma prioridade de um parâmetro explícito, sem criar um segundo
  mecanismo de resolução paralelo. **Adicionar contexto** (campo novo,
  entra no próximo prompt do agente via `_build_task`). **Solicitar ajuda**
  reaproveita `request_approval` (ação rotulada, sem mecanismo novo).
  **Pausar** ganhou uma reinterpretação honesta e restrita — impede a
  **próxima** execução (`run_card` recusa com 409), não interrompe uma já
  em andamento, já que nada no runtime suporta isso hoje. Das 7 "decisões
  do orquestrador" (wf §19.2), 6 mapeiam para ações reais; **"Criar
  investigação separada" fica desabilitada** com tooltip honesto — não
  existe esse mecanismo; "Bloquear" é rotulado honestamente como "Bloquear
  (card)", já que não existe bloqueio de demanda inteira. Diagnóstico e
  confiança de falha são **calculados na leitura**, nunca persistidos como
  palpite — nova função pura `confianca_diagnostico`: `"alta"` quando a
  falha veio de verificação nomeada da bateria (fato), `"baixa"` na
  heurística por palavra-chave — categórica, nunca um percentual, mesmo
  raciocínio já usado na confiança de recomendação de roteamento
  (ADR-0044). **Duração real por critério de quality gate**:
  `QualityGateEngine.run` mede `time.monotonic()` em volta de cada
  predicado (cobre comando externo e em memória uniformemente) — novo
  `GateCriterionResult.duration_ms`, migration na tabela normalizada
  `gate_criteria`. Novo `WorktreeManager.changed_files` (`git diff
  --name-only`) para "arquivos alterados" — lista vazia honesta quando o
  card nunca teve branch. "Plano passo a passo" do wireframe **não virou
  um checklist fictício** — nenhum mecanismo rastreia progresso granular
  por passo; a aba aponta para o `preparation_checklist` real já existente,
  sem inventar uma terceira fonte de verdade. `/ui/execucoes?id=` e
  `/ui/testes?id=` (2 das 16 seções fixas da sidebar) substituem os
  placeholders do FID-09 — listas agregadas por demanda com drill-down para
  `/ui/card-detalhe`, mesmo padrão kanban macro vs. kanban por card do
  FID-20; `/ui/testes` documenta honestamente que plano de teste
  manual/registro de bug (wf §20/§21) é escopo do FID-22, ainda pendente.
  Duas migrations novas, validadas em SQLite **e Postgres real via
  Docker**. Um bug real (ordem de validação em `transfer_card_model` —
  catálogo checado antes da existência do card) foi encontrado e corrigido
  pelos próprios testes antes de finalizar.
- **Kanban operacional completo (ADR-0047, FID-20):** wf §13 pede 14 colunas
  nomeadas, card resumido com 11 campos e movimentação manual respeitando a
  máquina de estados do wf §35. Investigação prévia encontrou uma dívida
  antiga: `specs/kanban.md` (TASK-04, ADR-0002) já listava "movimentos
  inválidos são rejeitados" como critério de aceite original — **nunca
  implementado**; `BoardService.move_card` sempre aceitou qualquer
  origem→destino. Este card paga essa dívida, não é escopo novo. Novo
  módulo puro `kanban/transitions.py`: grafo de transições válidas
  derivado do diagrama do §35, com os nomes do wireframe mapeados para as
  16 `ColumnKey` reais — "Pronto para implantação" e o estado transitório
  "Rollback" (sem `ColumnKey` própria) são colapsados honestamente em
  arestas reais adjacentes (Review→Deploying, Validating→NeedsFix),
  documentado explicitamente. **Validação só no caminho manual**: novo
  `OrchestrationService.move_card_validado`, usado exclusivamente pelo
  endpoint HTTP `POST .../move` — confirmado que **todos** os call-sites
  internos de automação (roteamento de falha, liberação de dependência,
  block/unblock/cancel) chamam `BoardService.move_card` diretamente, nunca
  através do método de serviço — zero risco a fluxos internos já maduros.
  Dois testes existentes que usavam o endpoint de mover como atalho de
  fixture (não testavam a máquina de estados) foram ajustados para uma
  transição válida. Novo `GET /v1/orchestrations/{id}/kanban`: as 16
  colunas reais (13 com rótulo literal do wireframe, 3 sem correspondência
  usando o nome do `ColumnKey`) com os cards trazendo os 11 campos do
  §13.3 **já resolvidos no backend** (agente/modelo/effort cruzados com o
  catálogo de executores e o ring de tentativas; indicador de aprovação
  humana pendente filtrado por `card_id`; falhas com indicador honesto de
  truncamento do ring de 5) — evita N+1 no cliente. Nova página
  `/ui/kanban?id=` substitui o placeholder do FID-09 — board de **uma**
  demanda (decisão explícita do usuário; o kanban macro `/ui/`, que agrega
  várias orquestrações, continua existindo à parte, intocado). Sem `?id=`,
  mostra um seletor de demandas. Drag-and-drop nativo HTML5, zero
  dependência externa nova — transição rejeitada mostra a mensagem real
  devolvida pelo backend e sempre recarrega o quadro do servidor, nunca
  move otimisticamente no cliente. `demanda-detalhe.html`: aba "Cards"
  ganhou um link para o Kanban completo.
- **Documentos, especificações e revisão documental (ADR-0046, FID-19):**
  wf §10 pede 13 tipos de documento (Requisitos, Especificação funcional,
  Especificação técnica, Arquitetura, Diagrama de componentes, Diagrama de
  fluxo, Modelo de dados, Contrato de API, Plano de migração, Plano de
  testes, Plano de implantação, Plano de rollback, Checklist de segurança).
  Investigação prévia mapeou: 1 tipo já era `SpecDocument` (entidade
  madura, com fluxo de revisão completo); 4 tipos já eram **campos**
  isolados dentro dele (a própria ADR-0021 já tinha decidido
  deliberadamente não dar campos próprios a eles); **8 tipos não tinham
  NENHUMA representação**. Nova entidade **genérica** `Documento`
  (`control/documento.py`) cobre só esses 8 — não 8 modelos Pydantic
  separados, seguindo o precedente já usado no projeto (`ContextPatch`/
  `DomainEvent`/o próprio ring genérico de `control/documentos.py`). **Os 5
  tipos já cobertos pelo spec continuam vivendo só lá, nunca duplicados**
  (decisão explícita do usuário sobre a alternativa de migrar tudo para o
  sistema novo) — a lista de documentos os mostra em modo leitura, lendo o
  dado real ao vivo do `SpecDocument`; tentar editá-los pela rota nova
  devolve `400` com mensagem explicando onde editar de verdade.
  **Achado decisivo, reaproveitado sem nenhuma mudança**: `DocReviewVerdict`/
  `ReviewService.revisar_documento` (ADR-0021) já tinha **exatamente** os
  quatro desfechos do wf §11.2 (aprovado / aprovado com observações /
  reprovado / necessita decisão humana) e já era genérico (aceita qualquer
  `BaseModel`) — o checklist do revisor dos 8 tipos novos reaproveita o
  motor inteiro, com um fluxo deliberadamente mais simples que o da spec
  (sem contagem de rodadas, sem exigir revisor diferente do autor — são
  artefatos de apoio, não o gate central de qualidade). Novo modelo
  `DocumentComment` (comparado campo a campo com `ReviewComment`/ADR-0033 —
  só 3 de 8 batiam — não reaproveitado) com os 8 campos literais do wf
  §10.3/§11.3: autor, tipo, severidade, trecho relacionado, descrição, ação
  solicitada, status, resposta do autor. Comparação de versões via
  `difflib.unified_diff` (stdlib, zero dependência nova). **Persistência**:
  duas colunas JSONB novas em `orchestrations` (não tabelas novas) — mesmo
  padrão de `discovery_reports`/`spec_documents`; migration validada não só
  em SQLite, mas em **Postgres real via Docker** (`docker compose up
  --build`, `/health`, `./scripts/smoke.sh`, além de um ciclo completo de
  criar/ler/editar/comentar documento contra o Postgres). Nova página
  `/ui/documentos?id=` substitui o placeholder criado no FID-09/ADR-0036
  (uma das 16 seções fixas da sidebar, reservada desde então) — editor
  Markdown com visualização renderizada por um "subconjunto simples"
  próprio (cabeçalhos, negrito, itálico, código, listas, links — não um
  parser CommonMark completo nem biblioteca externa nova, mantendo o
  precedente "zero dependência" das ADRs anteriores), histórico de versões
  com comparação, comentários e o checklist do revisor. Sem `?id=`, mostra
  um seletor simples de demandas em vez de redirecionar — é a primeira
  seção de primeiro nível da sidebar com conteúdo por-demanda, alcançável
  sem contexto prévio. `demanda-detalhe.html`: aba "Documentos" ganhou um
  link para a página completa.
- **Discovery técnico e sua aprovação (ADR-0045, FID-18):** expande a aba
  "Discovery" já existente em `demanda-detalhe.html` (não uma página nova)
  com painel de execução, log real e checklist de aprovação. `DiscoveryReport`
  ganha `started_at`/`finished_at`/`duration_ms`/`log` — timestamps e
  duração **reais**, medidos com `time.monotonic()` dentro de
  `DiscoveryService.investigar()`; `log` é uma lista curta de eventos reais
  (início com executor/effort, desfecho com confiança ou motivo de falha),
  nunca uma linha fabricada como o exemplo ilustrativo do wireframe. Escopo
  de "logs ao vivo" **refinado durante a implementação**: investigação
  revelou que streaming verdadeiro (token a token, enquanto a chamada
  ainda está em voo) exigiria portar o padrão `Popen`+threads+`AgentLogBus`
  (já usado em `cli_provider.py` para execução de card) para
  `agent_ask.py::perguntar_ao_agente` — função compartilhada por **5
  serviços** (naming, triagem, revisão, discovery, especificação); em vez
  desse raio de impacto desproporcional, entregue timing+log reais
  pós-execução, decisão documentada explicitamente, não escondida. As 7
  "Etapas da análise" do wireframe **não** viraram um checklist fictício —
  a chamada ao agente é uma única operação, sem sub-passos observáveis; a
  aba mostra uma nota honesta em vez de progresso granular fabricado.
  **Checklist de aprovação com os 7 rótulos literais do wireframe**
  (decisão explícita do usuário, não a alternativa recomendada de mostrar
  só os 3 reais) — nova função pura `avaliar_criterios_aprovacao`: 3 itens
  com verificação automática real (risco, mudança de arquitetura, risco de
  perda de dados via impacto "database", confiança do agente), os outros 4
  ("Escopo claro", "Sem impacto financeiro significativo", "Padrões já
  aprovados") ficam com tooltip honesto "sem verificação automática hoje",
  nunca um resultado fabricado. `motivos_escalada` é 100% real — satisfaz
  o critério de aceite "motivos da escalada humana listados explicitamente",
  que antes não existia como texto algum. Novo `GET
  .../discovery/approval-criteria`. As 4 ações de aprovação (Reprovar,
  Solicitar ajustes, Aprovar com observações, Aprovar) mapeiam
  honestamente para as 2 operações reais já existentes
  (`decide_discovery(approved: bool)`) — documentado como simplificação de
  UX, não 4 estados novos persistidos; zero mudança de backend para as
  ações em si. Painel de execução (agente/modelo/effort/status/tempo
  decorrido) reaproveita `agent_assignments["discovery"]` cruzado com o
  catálogo de executores, mesmo padrão do painel de responsáveis da Tela
  04. Botão "Rodar discovery" reaproveita `POST .../discovery/run`, que já
  existia (usado até agora só em `detalhe.html`). Correção retroativa em
  `docs/mapa-paginas.md`: as linhas "Modelos"/"Aprovações" citavam
  FID-17/FID-18 especulativamente desde o FID-09 — corrigidas agora que
  suas implementações reais confirmaram que ambos vivem dentro de
  `demanda-detalhe.html`, não em `/ui/modelos`/`/ui/aprovacoes`.
- **Classificação editável e painel de recomendação (ADR-0044, FID-17):**
  duas abas novas em `demanda-detalhe.html` — "Classificação" (wf §7, Tela
  05) e "Recomendação" (wf §15, Tela 13) — não uma página satélite nova,
  já que ambas falam da mesma demanda já em foco na Tela 04 (a própria
  descrição do card confirmava: "a classificação aparece na ficha").
  **Classificação editável**: novo `PATCH /v1/orchestrations/{id}/classification`,
  edição pontual (só os campos informados mudam), diferente de
  `retriage_demand` (que reroda o agente de triagem inteiro do zero) —
  evento auditável `ClassificationUpdated` com `before`/`after`, mesmo
  padrão estrutural já usado por `ExecutionSettingsUpdated`, aparecendo
  automaticamente na aba Histórico. **Painel de recomendação**: novo `GET
  /v1/orchestrations/{id}/recommendation` — método novo e independente
  (`preview_recommendation`), escolha explícita do usuário sobre a
  alternativa de refatorar `create_orchestration`/`_apply_routing_rule`
  (caminho crítico já em produção) para compartilhar lógica; reaproveita as
  mesmas funções puras do caminho real (`avaliar_regras`+
  `contexto_de_demand_brief`, mesmo par do FID-15/ADR-0042; e, sem regra
  casando, `MultiAgentDecisionEngine.decide`+`sugerir_effort`), só que
  somente leitura, sem persistir nada. **Confiança é categórica** (`"alta"`
  quando uma regra bateu, `"baixa"` no fallback heurístico) — decisão
  explícita do usuário: nunca um percentual fabricado, já que o motor não
  produz nenhum número de confiança (o "92%" do wireframe é só exemplo
  ilustrativo). **Custo/tempo estimados** derivados do histórico GLOBAL de
  desempenho (`GET /v1/learning`, `desempenho_por_executor`), bucketados em
  terços (baixo/médio/alto) pela posição relativa do executor recomendado —
  `null` quando não há modelo recomendado (heurística não recomenda modelo)
  ou não há amostra desse executor no histórico. **"Override humano da
  recomendação registrado"** reaproveita 100% o `PATCH .../execution-settings`
  já existente (que já gravava `ExecutionSettingsUpdated`) via um botão
  "Aplicar como override manual" na aba Recomendação — nenhum mecanismo de
  override novo foi inventado. "Prioridade" continua sendo o mesmo campo
  que `risco` (convergência já documentada nas ADR-0038/0039); "quality
  gates necessários" vêm de `RoutingAction.quality_gates` quando uma regra
  bate; "número estimado de cards" é omitido por completo — não existe
  mecanismo real que produza essa estimativa hoje.
- **Detalhes da demanda em 11 abas (ADR-0043, FID-16):** `detalhe.html` é a
  "sala de controle" legada (esteira F1→F7, próximo passo, SSE ao vivo) que
  a ADR-0036 (FID-09) tinha deixado explicitamente sem sidebar — mas essa
  mesma ADR já previa que os cards FID-10…FID-26 iriam "absorver" o conteúdo
  das páginas legadas para dentro das seções novas. Este card é essa
  absorção: nova página satélite `/ui/demanda-detalhe?id=&aba=`, mesmo
  padrão dos satélites anteriores (header+sidebar `active:'demandas'`,
  componente `.tabs`/`.tab` já usado no FID-14) — **`detalhe.html`
  permanece 100% intocada**, seguindo o mesmo precedente do FID-14/ADR-0041
  (página nova + redirecionamento dos pontos de entrada, não edição da
  página legada no lugar). Cabeçalho com os 11 campos do wf §6.2 (código,
  status, prioridade/risco — mesmo campo único desde a ADR-0038/0039 —,
  complexidade, impacto, projeto, solicitante, data de criação). **Barra de
  progresso** = cards Done / total de cards da demanda inteira (fórmula não
  especificada pelo wireframe, decidida com o usuário — mesma lógica já
  usada para o progresso da FASE atual em `next_step.py`, agora aplicada à
  demanda inteira); reaproveita `.progressbar`, componente CSS comentado
  desde a origem como "wf §6.4" e nunca consumido até agora. **Painel de
  responsáveis** usa `agent_assignments` real (10 etapas técnicas: F1-F7 +
  `naming`/`triagem`/`revisao`), cruzado com `GET /v1/executors` para
  resolver o modelo — não os 4 papéis ilustrativos do exemplo do wireframe
  ("Orquestrador/Arquiteto/Implementação/Review"), que não correspondem a
  nenhuma chave real do domínio. **SSE mantido ao vivo** (decisão do
  usuário, não a alternativa mais simples de fetch único) — primeira página
  satélite do projeto com `EventSource`; reaproveita o mesmo endpoint de
  `detalhe.html`, mas cada evento recarrega só o núcleo + a aba **ativa**
  (carregamento tardio por aba, com cache), não a página inteira. **Zero
  endpoint novo** — as 11 abas (Visão geral, Discovery, Documentos, Cards,
  Execuções, Testes, Reviews, Deploys, Incidentes, Histórico, Métricas)
  consomem 17 endpoints já existentes de cards anteriores; "Documentos"
  agrega Discovery+Spec+ADRs (a lista completa de tipos de documento do wf
  §10 é escopo do FID-19, não deste card). `demandas.html`: "Visualizar
  histórico"/"Visualizar documentos" agora apontam para a nova página com
  deep-link direto à aba certa; "Abrir" continua em `/ui/detalhe` — a única
  ação de console que permanece lá.
- **Editor visual de regras de roteamento (ADR-0042, FID-15):** camada de UI
  pura sobre o motor SE/ENTÃO já entregue no FID-01/ADR-0028 — o wireframe
  §33 descreve o editor de condições/ações, mas **não menciona** pré-
  visualização de demandas nem ordem de precedência editável em nenhum
  lugar; os dois critérios extras do card são extrapolações sobre a spec
  original, documentadas como tal na ADR, não escondidas. Pré-visualização
  real via novo `POST /v1/routing-rules/preview`: roda `avaliar_regras()`
  (motor puro do FID-01, zero duplicação de lógica no frontend) contra
  `list_all()` — todas as demandas já existentes no sistema, leitura leve
  sem hidratar bundle, mesma filosofia "dev-scale" já aceita em
  `header_summary`/`search` (ADR-0035). Nova função pura
  `contexto_de_demand_brief`, espelhando `contexto_de_decision_input` já
  existente. Ordenação por **arrastar-e-soltar** (escolha explícita do
  usuário, não a alternativa recomendada mais simples de campo numérico por
  linha) via novo `PUT /v1/routing-rules/reorder`, reatribuindo
  `precedencia` sequencial (10, 20, 30…) — registrada **antes** de `PUT
  .../{rule_id}` para não ser interceptada como `rule_id="reorder"` (mesmo
  cuidado de ordenação de rotas Starlette já aplicado a `cards/{card_id}`
  na ADR-0041, com teste de regressão dedicado). "Escrita restrita a admin"
  já estava implementado desde o FID-01 (`auth.py::required_role`, checagem
  por prefixo `/routing-rules`) — nenhuma mudança de RBAC foi necessária;
  `preview`/`reorder` herdam a exigência automaticamente por caírem no
  mesmo prefixo (`preview`, embora só leitura, também exige admin por esse
  motivo — aceito para não introduzir exceção pontual no middleware).
  Campos "Agente"/"Effort" seguem texto livre (não existe catálogo global
  desses valores); "Modelo" vira `<select>` populado por `GET /v1/executors`
  (dado real). Nova página satélite `/ui/regras-roteamento` — primeira do
  projeto **sem** `?id=`, já que regras são configuração global, não de uma
  demanda específica — linkada a partir de `/ui/console` até `/ui/configuracoes`
  (FID-26) existir.
- **Detalhes do card em 10 abas (ADR-0041, FID-14):** o wireframe §14 lista os
  campos obrigatórios (§14.1) e os nomes das 10 abas (§14.2) em duas listas
  separadas, sem cruzamento — o mapeamento campo→aba (Resumo, Plano,
  Implementação, Arquivos, Testes, Review, Evidências, Dependências,
  Execuções, Histórico) é decisão de design deste ADR, não citação literal do
  wireframe. Objetivo/Contexto/Riscos/Evidências esperadas/Complexidade não
  têm granularidade de card — só existem no `DemandBrief` da orquestração —
  e são reaproveitados na aba Resumo com rótulo explícito "herdado da
  demanda", por escolha confirmada com o usuário (reaproveitar rotulado, não
  omitir, e não fabricar campo novo). Modelo selecionado e Nível de effort
  também não são campos estáticos: só existem por tentativa
  (`TentativaRegistro.executor`/`.effort`, ring `tentativas`), mostrados na
  aba Execuções. **"Histórico de execução nunca sobrescrito" cumprido de
  forma real**: novo endpoint `GET .../cards/{card_id}/events` expõe pela
  primeira vez via HTTP o `BoardService.card_events` — log append-only já
  coletado e persistido integralmente desde a ADR-0025/ADR-0019, mas nunca
  servido — diferente dos rings `failures`/`tentativas`/`qa_checks`
  (truncados em 5/10/10, usados nas abas Execuções/Testes, não na
  Histórico). Novo `GET .../cards/{card_id}` devolve a ficha completa de um
  único card. Cuidado de roteamento explícito: essa rota (path param de um
  segmento) foi registrada **depois** de `cards/tree`, `cards/stats` e
  `cards/by-status/{status}` para não sombreá-las — Starlette casa rotas por
  ordem de registro — com teste dedicado para não repetir essa classe de bug.
  Nova página satélite `/ui/card-detalhe?id=&card=`, reaproveitando o
  componente `.tabs`/`.tab` já existente desde o design system (ADR-0034,
  até agora só usado no console legado). `demanda-estrutura.html` (FID-13):
  clique no nó da árvore agora navega para `/ui/card-detalhe`, fechando a
  lacuna de deep-link que a ADR-0040 havia documentado como limitação
  honesta.
- **Estrutura da demanda em árvore (ADR-0040, FID-13):** o próprio wireframe §12 só
  desenha 3 níveis (Épico/História/Card) — "Subtarefa" (citada na descrição do card)
  não aparece em nenhum texto nem diagrama da seção-fonte. Usuário aprovou
  explicitamente subir `PROFUNDIDADE_MAXIMA` de 3 para 4 em `hierarchy.py`: "Subtarefa"
  não é um `CardType` novo, é o mesmo `TASK` com `parent_id` apontando para outro
  `TASK`. `montar_arvore(cards)` — função pura nova, recursiva sobre `filhos()` (que
  já existia) — monta a árvore completa pela primeira vez; até aqui `hierarchy.py`
  (ADR-0025) só tinha primitivas de nível único. "Projeto" vira rótulo estático de
  contexto no topo da tela, **não** um nó expansível: a árvore é de **uma demanda**
  específica (uma orquestração), não do projeto inteiro — `Project` agrupa
  orquestrações, não cards, e o wireframe nem desenha esse nó. "História" reaproveita
  `CardType.FEATURE` (já usado com esse papel), sem enum novo. Dois endpoints novos:
  `GET .../cards/tree` e `POST .../cards` (cria item em qualquer nível, reaproveitando
  `BoardService.add_card` integralmente — `parent_id` inexistente/ciclo/profundidade
  excedida devolvem `409` com a mesma mensagem da validação interna). Navegação do nó
  volta para `/ui/detalhe?id=`, sem destacar o card específico (não existe deep-link a
  card dentro do detalhe hoje — documentado, não escondido). Correção retroativa em
  `demandas.html` (FID-11): "Visualizar cards" agora aponta para a Tela 10, não mais
  para o detalhe legado. O componente `.tree` (criado no FID-07, nunca usado até
  agora) finalmente tem uma tela consumindo-o.
- **Cadastro de demanda completo (ADR-0039, FID-12):** `DemandBrief` ganha 11 campos
  novos, todos aditivos (`solicitante`, `origem_da_demanda`, `sistemas_afetados`,
  `apis_afetadas`, `banco_de_dados_afetado`, `infraestrutura_afetada`,
  `dependencias_conhecidas`, `restricoes`, `evidencias_esperadas`,
  `aprovacao_humana_obrigatoria`, `prazo`) — investigação prévia achou que só 8 dos
  ~24 campos do wireframe §5.2 já tinham correspondência; "Prioridade" continua sendo
  o mesmo valor de "Risco" (confirma o achado do FID-11), sem campo separado.
  **`aprovacao_humana_obrigatoria` tem efeito real**: força
  `plan.requires_human_approval` na criação, mesmo precedente que
  `RoutingRuleAction.aprovacao_humana` (ADR-0028) já tinha — testado de ponta a ponta
  com dado real. `orcamento_usd` passa a ser aceito já na criação (antes só via
  `PUT .../budget`). `POST /v1/orchestrations` ganha um segundo caminho, documentado
  como exceção deliberada ao "único caminho correto de criação" (ADR-0017): quando o
  corpo já traz uma `demand_brief` completa, cria direto sem re-triagem — o
  solicitante já preencheu a ficha à mão. Bug real identificado e corrigido antes de
  finalizar: sem construir o `decision_input` a partir da ficha, o motor de decisão
  ignoraria silenciosamente os domínios/impactos/risco escolhidos pelo usuário.
  Página nova `/ui/demanda-nova` (não mexe em `nova.html`, página legada congelada
  pela ADR-0036) com os 4 blocos do wireframe, "Salvar rascunho"/"Iniciar" como ações
  distintas — sem disparar Autopilot automaticamente.
- **Lista de demandas com filtros e ações (ADR-0038, FID-11):** investigação prévia
  (mesmo padrão do FID-10) achou que 4 das 11 ações do wireframe §4.4 não têm nenhum
  backend hoje (Editar, Duplicar, Priorizar, Bloquear) e que "Prioridade" não existe
  como campo de demanda — só como espelho do `risco`. Usuário aprovou: 7 ações reais
  com endpoint já existente + **Duplicar** implementado agora (`POST
  .../orchestrations/{id}/duplicate`, re-triagem do zero pelo caminho de
  `create_with_triage`, sem clonar cards/histórico) + Editar/Priorizar/Bloquear
  desabilitadas com motivo explícito no tooltip, sem fingir funcionalidade. Filtro
  "Prioridade" converge com "Risco" num único controle real (mesmo campo). **Risco de
  performance identificado e evitado antes de codificar**: o jeito óbvio de calcular
  "aprovação humana" (reaproveitar `list_all_approvals()`) hidrataria toda orquestração
  do sistema a cada chamada de uma tabela paginada — resolvido com uma query nova e
  direta (`orchestration_ids_with_pending_approval`, sobre índice já existente, sem
  hidratar nenhum bundle). 6 filtros baratos (`project_id`/`status`/`q`/`executor`/
  `created_from`/`created_to`) rodam em SQL; os 5 que dependem de `demand_brief` (JSON
  sem índice) ou de aprovação pendente rodam em memória sobre o resultado já reduzido
  pelos baratos — nunca sobre todas as orquestrações. `GET /v1/orchestrations` sem
  `page` continua devolvendo tudo que bate no filtro (contrato preservado). Primeira
  tabela paginada com filtros persistidos na URL (`history.replaceState`) do projeto.
- **Dashboard operacional (ADR-0037, FID-10) — primeira das 16 seções da sidebar com
  conteúdo real:** investigação prévia revelou que a maioria dos dados pedidos pelo
  wireframe §3 não tem fonte real hoje — cada lacuna virou decisão explícita, duas
  confirmadas com o usuário. **Sem campo de "variação"**: nenhuma série temporal dos
  indicadores globais existe em lugar nenhum do sistema (`SloEvaluation`, o único
  histórico com timestamp, é por orquestração, sobre outra coisa, e só gravado sob
  demanda) — os 4 cards de indicador mostram só título, valor e link, sem número
  fabricado. **Diagrama do fluxo via `mermaid.js` carregado por CDN** — escolha
  explícita do usuário entre duas opções oferecidas; é a **primeira dependência
  externa do frontend**, rompendo conscientemente o precedente "zero dependência" das
  ADR-0034/0035/0036, escopada só a `dashboard.html` (testado que as outras 19
  páginas continuam sem nenhuma lib externa). `HumanApproval` ganha o campo `tipo`
  (migration nova), preenchido nos 3 pontos reais de criação automática de aprovação
  (`estrategia`/`patch`/`fase_gate`) — **não** os 4 rótulos fictícios do wireframe
  (Discovery/Arquitetura/Deploy/Aceite final), que não existem no runtime.
  "Bloqueadas" reaproveita o status real `waiting_human` — não existe (nem este card
  cria) nenhum status `blocked` de orquestração. `GET /v1/dashboard-summary` (escopado
  por projeto) e `GET /v1/activity` (atividade global nova, query única sem N+1, ao
  contrário da timeline por orquestração) são os dois endpoints novos.
- **Sidebar de 16 seções e mapa de páginas (ADR-0036, FID-09) — fecha a Trilha B:**
  último card do shell da interface, desbloqueando os 17 cards de tela restantes
  (FID-10…FID-26). Nenhum card cobre hoje o conteúdo de nenhuma das 16 seções — este
  card entrega infraestrutura de navegação (rotas + sidebar + mapa), não conteúdo: 16
  arquivos HTML novos + 16 rotas explícitas (mesmo padrão das 4 páginas já existentes,
  **não** um roteador client-side — preserva o precedente "zero bundler" das
  ADR-0034/0035), cada um um placeholder honesto (título, "ainda não implementada —
  acompanhe FID-XX", link para a página legada que cobre parcialmente aquele conteúdo
  hoje, quando existe). `static/sidebar.js` — segundo JS compartilhado do projeto —
  calcula a seção ativa a partir de `location.pathname`, sem estado extra no cliente.
  Decisão crítica evitada antes de virar bug: as rotas são registradas por **nome
  fixo** (`app.add_api_route` em laço com fábrica de handler), não um path curinga
  `/ui/{secao}`, que interceptaria `tokens.css`/`components.css`/`header.js` antes do
  `StaticFiles` mount — travado por teste dedicado. As 4 páginas legadas (`/ui/`,
  `/ui/nova`, `/ui/detalhe`, `/ui/console`) **não** ganham a sidebar (cada uma mistura
  conteúdo de várias seções, sem uma "seção ativa" única e honesta) — continuam
  válidas, intocadas. `docs/mapa-paginas.md` novo, satisfazendo o entregável do
  wireframe §40 (mapa das páginas + estrutura de rotas).
- **Header compartilhado com os 9 elementos da spec (ADR-0035, FID-08):**
  `static/header.js` — primeiro JS compartilhado do projeto (as 4 páginas eram
  autocontidas até aqui). Diferente do design system (FID-07, puro reskin), este card
  é funcionalidade nova com dados ao vivo — 9 elementos duplicados 4x seria pior que o
  problema que o CSS compartilhado resolveu. O wireframe §2.3 não detalha 4 dos 9 itens
  (notificações, busca, ambiente, perfil) — decisão: reaproveitar dado que já existe em
  vez de inventar (notificações = aprovações pendentes; ambiente = só leitura, nenhuma
  ação de "trocar" existe no resto do sistema; perfil = `actor`/`role` via novo
  `GET /v1/me`, já que não há usuário nomeado no runtime, só token→papel). Backend
  novo: `GET /v1/me`, `GET /v1/header-summary?project_id=` (execuções ativas/falhas/
  aprovações pendentes, escopado ou global), `GET /v1/search?q=&project_id=` (busca
  substring em demanda/card/documento), filtros `status`/`project_id` em
  `GET /v1/approvals`. Cada página troca seu `<header>` duplicado por
  `<header id="app-header">` + `ASOHeader.mount(...)` — resolve de passagem uma
  inconsistência real pré-existente (campo de token `#tok` em uma página, `#token` nas
  outras 3; handler `saveTok()` global vs. listener `#login`). `detalhe.html` ganha um
  `.orquestracao-banner` separado do `<header>` para os breadcrumbs/título/fatos
  daquela orquestração específica (conteúdo de página, não navegação do app).
  Indicadores por polling de 20s (sem SSE global — só existe stream por orquestração
  hoje). Sem regressão nos 3 testes que travam texto literal das páginas.
- **Design system wireframe: tema claro, tokens e componentes reutilizáveis (ADR-0034,
  FID-06➜07):** `static/tokens.css` + `static/components.css`, extraídos LITERALMENTE
  (mesma regra, mesmo seletor, só recolorida — não um redesenho) do CSS 100% inline que
  cada uma das 4 páginas de `/ui/*` duplicava por conta própria (com uma inconsistência
  real de nome: `--panel2` em três arquivos, `--panel-2` no quarto). Zero mudança de
  `<script>`/markup em qualquer página — o precedente da ADR-0013 (lógica de governança
  no backend, tela só renderiza) fica intacto. Paleta clara neutra concreta (o wireframe
  §2.1 só pede princípios — fundo claro, tons neutros, bordas visíveis — sem valores
  hex): `--bg:#f8fafc`, `--accent:#0284c7` (mais escuro que o `#38bdf8` antigo, por
  contraste), semânticas em tom 600. Biblioteca documentada em `docs/design-system.md`:
  card, botão (dois padrões `button`/`.btn` preservados lado a lado), pill de status,
  tabela, checklist, **árvore** (componente novo, wf §12, para uma tela futura), abas,
  painel de logs/timeline, barra de progresso (3 nomes de classe históricos unificados),
  kanban, overlay/modal, grid responsivo. Corrige de passagem o painel "ao vivo do
  agente", que tinha fundo escuro fixo (`#0a1220`) independente do tema — virava um
  retângulo incongruente numa página clara. Escopo deliberadamente contido: sem
  header/sidebar ainda (isso é FID-08/FID-09, que dependem deste card).
- **Comentário de revisão ancorado em arquivo/linha (ADR-0033, FID-06):** `ReviewComment`
  (`governance/models.py`) ganha identidade própria — mesmo padrão de `PullRequest`/
  `Incident` — de forma ADITIVA: `ReviewVerdict`/`ReviewAction`/`PullRequest.review_verdict`
  continuam existindo e populados exatamente como a ADR-0017 deixou (nenhum consumidor
  existente muda de comportamento). Reverte, só para este caso, a decisão "sem tabela
  filha" da ADR-0017 — cada comentário tem ciclo de vida próprio de resolução
  (`pendente`/`resolvido`), diferente do veredito agregado. Os 8 campos do wireframe
  §20.3: `arquivo`, `linha`, `categoria`, `severidade` (`baixa|media|alta|critica`,
  vocabulário de `QaCheck.gravidade` — campo **distinto** do `obrigatoria|sugestao` de
  `ReviewAction.severidade`, como o wireframe pede), `descricao`, `sugestao`,
  `obrigatorio`, `status`. O agente revisor passa a devolver um array `comentarios` ao
  lado de `acoes` (fallback vazio quando só devolve `acoes`, comportamento anterior —
  zero regressão). Uma rodada de review que aprova auto-resolve os comentários
  obrigatórios pendentes da PR (reflete o ciclo do §15: correção → testes → nova revisão
  →(aprovado) próxima etapa); `POST .../comments/{id}/resolve` cobre a resolução manual.
  `card.correction_actions` passa a derivar dos comentários quando existem, com
  fallback para o caminho legado (`acoes`) quando não existem. `merge_pr` ganha uma
  segunda trava: recusa com qualquer comentário obrigatório pendente, mesmo com
  `review_status` já `approved` (cobre aprovação humana com justificativa, que não
  passa pela auto-resolução). `next_step` ganha o bloqueio
  `pr_comentario_obrigatorio_nao_resolvido`, com `arquivo:linha`.
- **Incident como entidade de primeira classe (ADR-0032, FID-05):** `Incident` +
  `IncidentTimelineEntry` (`governance/models.py`) ganham identidade própria — mesmo
  padrão de `PullRequest`/`CandidateRun`/`SloEvaluation` — em vez de mais um campo
  dentro de `KanbanCard`; é a primeira entidade do projeto com `timeline` embutida,
  porque um incidente é um objeto de vida longa que muda de estado, não um evento
  imutável. `rollback_deploy` continua criando o `KanbanCard(Incident)` exatamente
  como antes (zero regressão) e passa a vincular um `Incident`: gravidade derivada do
  risco da demanda (`_RISCO_PARA_GRAVIDADE`, mesmo vocabulário baixa/media/alta/critica
  de `QaCheck.gravidade`), snapshot do deploy revertido (ambiente/estágio/versão, sem
  FK — `DeployRun` não tem id próprio). Ciclo de vida `aberto → investigando →
  resolvido` (resolver exige causa raiz; incidente resolvido não reabre nem resolve de
  novo). Endpoints `GET /incidents`, `GET /incidents/{id}`, `POST .../investigate`,
  `POST .../resolve`. Sem backfill de cards `INCIDENT` anteriores — decisão consciente
  documentada na ADR, mudança 100% aditiva.
- **Limite de tentativas por card (ADR-0031, FID-04):** corrige um bug real —
  `len(card.failures)` (ring travado em 5) era usado como contador de
  tentativas; reroteamento manual repetido sobre um card `Failed` travava o
  rótulo "tentativa N" em 5 para sempre, mesmo depois de dezenas de
  reroteamentos. `KanbanCard.tentativa_atual` (contador autoritativo, nunca
  truncado) substitui essa contagem; `max_tentativas` (`None` = usa o teto
  global do processo) e `tentativas` (histórico completo por tentativa, sucesso
  **e** falha, com modelo/effort/resultado) são novos. `RoutingRule.acao.
  limite_tentativas` (persistido desde a ADR-0028 mas nunca aplicado) passa a
  ser herdado por todos os cards nascidos numa orquestração cuja regra casou.
- **Checklist de preparação e tarefa vinculada (ADR-0030, FID-03):** os 8 itens do
  `fluxo.md` §10 (especificação lida, critérios de aceite analisados, código
  afetado analisado, dependências verificadas, testes existentes identificados,
  branch criada, plano de execução registrado, card desbloqueado) deixam de ser
  implícitos — passam a ser marcados automaticamente durante a execução do card
  (nunca manualmente: não há `POST`, só `GET /cards/{id}/checklist`), com autor e
  timestamp. Bloqueio por dependência pendente (já existia desde a ADR-0018) ganha
  criação automática e idempotente de uma tarefa vinculada
  (`KanbanCard(type="Task", status="Backlog")`) para o operador acompanhar a
  resolução. O checklist aparece na ficha de encerramento do card (§23).
- **Pipeline de implantação multi-estágio (ADR-0029, FID-02):** `DeployRun.ambiente`
  deixa de ser só uma string livre — o operador configura um pipeline de estágios
  (`Environment`: chave/ordem/comando/health checks/rollback/exige aprovação humana,
  `PUT .../deploy/pipeline`) com avanço governado (`POST .../deploy/run` recusa
  pular um estágio antes do anterior concluir). Falha de implantação é classificada
  em cinco diagnósticos do `fluxo.md` §19 (build/configuração/migration/pós-deploy/
  crítica — crítica é sempre uma validação pós-deploy reprovada **em produção**,
  fato, não heurística) e nunca fica sem próxima ação nomeada; falha crítica
  recomenda rollback com a maior ênfase possível, mas nunca executa
  automaticamente — continua exigindo `POST .../deploy/rollback` por `admin`.
  Sem pipeline configurado (o padrão), o comportamento é idêntico ao monoambiente
  da ADR-0023; o gate F6 (`deploy_aprovado`) só exige todos os estágios concluídos
  quando há pipeline.
- **Regras de roteamento SE/ENTÃO (ADR-0028, FID-01):** o operador agora declara
  política de decisão — `RoutingRule` (condições sobre tipo/risco/complexidade/
  domínios/impactos, ações de agente/modelo/effort/aprovação humana/quality
  gates/limite de tentativas, precedência explícita) é avaliada **antes** do
  `MultiAgentDecisionEngine`/`selecao.py`, que continuam servindo de fallback puro
  quando nenhuma regra casa — nenhuma orquestração existente regride. Uma regra
  casando nunca sobrescreve uma escolha explícita do operador nem rebaixa uma
  aprovação humana já exigida pela heurística. CRUD via
  `GET/POST/PUT/DELETE /v1/routing-rules`, escrita restrita a `admin`. Fecha a
  maior lacuna funcional apontada em
  [docs/plano-fidelidade-fluxo.md](docs/plano-fidelidade-fluxo.md).
- **Custo real, orçamento com freio e sobrevivência a crash (ADR-0026,
  ADR-0027):** o runtime jogava fora o custo real que os agentes já
  informam (`observability/metrics.py` aproximava custo por tempo de
  execução, um proxy ruim — dois agentes de 30s podem diferir em 50× no
  valor pago). `execution/agent_stream.extrair_uso` lê `usage`/
  `total_cost_usd` do envelope `result` do Claude Code; a porta
  (`UsoDoAgente`) vive em `shared/agent_usage.py` (mesma solução da
  ADR-0015, `execution` não pode importar `observability`). `card.uso`
  acumula reexecuções (`acumular_uso`) e chega ao `closure` (§23) e ao
  relatório de aprendizado (`custo_total_usd`, `custo_por_entrega`,
  `execucoes_sem_custo`) — custo desconhecido nunca é somado como custo
  zero. `ASO_ORCAMENTO_PADRAO_USD`/`PUT /budget` (admin) definem um teto
  opcional; estourado recusa **nova** execução (`POST .../run`/`.../race`
  devolvem `409`) sem matar a que está rodando, e intercepta o roteamento
  de falha (ADR-0019): antes de `aumentar_effort`/`trocar_executor`, o
  freio vira `escalar_humano` com motivo de orçamento — é o ponto central
  do incremento, o freio que faltava para operar com dinheiro real. Isto
  também remove o motivo pelo qual o §9 (escolha automática de agente,
  declinada na ADR-0025 "por falta de dado") estava congelado — `custo_por_
  entrega` é exatamente o dado que faltava; a ADR-0025 foi emendada
  registrando a decisão como reavaliável, não mais bloqueada.
  Sobrevivência a crash (ADR-0027): card `InProgress` parado além de
  `ASO_AGENT_TIMEOUT` vira bloqueio `card_orfao` em `next_step`, roteado
  por `POST .../cards/{id}/route` (sem caminho novo de recuperação);
  `GET/POST .../worktrees` (`/prune`, admin) lista e remove worktrees
  órfãos via `git worktree remove` + `prune` (nunca `rm -rf`) sem tocar o
  banco — complementa `scripts/reset.sh`, que resolve o mesmo problema
  apagando tudo. 815 testes (34 novos), 92%+ cobertura, validado em
  Docker/Postgres (custo real capturado do envelope fake até o relatório
  de aprendizado, orçamento estourado bloqueando `run_card` e liberado ao
  elevar o teto, worktree órfão detectado e removido pelo `prune` sem
  tocar o banco).
- **QA humano, hierarquia de cards e aprendizado da esteira (ADR-0025):**
  fecha `fluxo.md` §7, §16, §17 e §24 — as últimas lacunas nomeadas nos
  planos anteriores. QA manual (§16/§17): `POST /cards/{id}/qa` registra uma
  verificação (cenário, passos, ambiente, resultado esperado/obtido,
  evidências, gravidade), exigida por `exige_qa_manual` (domínio `frontend`,
  complexidade `complexa`/`estrategica`, ou card `Epic`/`Feature`) e
  informada em `next_step` (`qa_pendente`/`qa_reprovado`); `POST
  /qa/{i}/fail` cria um card `Bug` vinculado (`dependencies` + `parent_id`
  quando a hierarquia permitir) e registra a falha no roteamento existente
  (`control/failure.py`, novo diagnóstico `falha_de_qa`, sem taxonomia
  nova). Hierarquia (§7): `KanbanCard.parent_id` — profundidade máxima 3,
  ciclo é erro, pai não fecha antes dos filhos, cancelar o pai cancela os
  filhos; produzida por `SpecWorkItem.itens_filhos` e `BacklogItem.type`.
  Pendência nomeada três vezes desde `plano4.md`, fechada. Aprendizado
  (§24): `observability/aprendizado.py` (puro — não importa `control`) agrega
  por executor (execuções, falhas, retrabalho, tempo, rodadas de revisão,
  erros recorrentes) a partir do que já estava persistido; `GET
  /orchestrations/{id}/learning` e `GET /learning` (consolidado).
  Informativo por decisão: não realimenta nenhuma decisão automaticamente —
  por isso o §9 (escolha de agente/modelo) é declarado formalmente como
  decisão manual, não pendência, reavaliável quando o relatório tiver massa
  de demandas reais. 781 testes, 92%+ cobertura, validado em Docker/Postgres
  (QA pendente→registrado→reprovado→bug criado→card bloqueado; profundidade/
  ciclo/fechamento de hierarquia; relatório de aprendizado consolidado).

- **Implantação governada (ADR-0023, "Incremento F"):** fecha `fluxo.md`
  §18-22 dentro do escopo real do MVP — o runtime não provisiona
  infraestrutura (deploy automático/provisionamento cloud continuam excluídos
  por `requerimentos.md`), mas governa um comando de implantação configurável
  pelo operador, exatamente como a bateria de validações (ADR-0022) já governa
  testes/lint. **Não confundir com `docs/deploy.md`**, que é sobre implantar
  o ASO Runtime em si — este incremento é sobre o runtime rastrear
  implantações dos projetos que ele orquestra. `PUT /deploy/config`
  (comando/ambiente/health checks/rollback, cada comando validado por
  `validate_gate_command`); `POST /deploy/run` exige o comando configurado e o
  último quality gate `PASSED` (§18) e sempre executa — a decisão humana é
  sobre aceitar o resultado, não sobre autorizar a tentativa (mesmo raciocínio
  do discovery, ADR-0020): falha vai direto a `reprovado`; sucesso aplica
  risco alto/crítico, impacto sensível ou validação reprovada →
  `aguardando_aprovacao` (`POST /deploy/approve`, admin), senão aceite
  automático. `POST /deploy/validate` roda as verificações pós-implantação
  (§20, reaproveita `ValidationCheck` da ADR-0022). `POST /deploy/rollback`
  (admin) marca a implantação como revertida e sempre abre um
  `KanbanCard(type="Incident")` em `Backlog` — a tarefa de causa raiz do §21.
  Implantações versionadas em ring de até 5 (`control/documentos.py`,
  reaproveitado pela terceira vez). Gate de F6 ganha o critério
  `deploy_aprovado` só quando alguma implantação já rodou — nenhuma
  orquestração existente muda de comportamento. Fecha as três referências
  pendentes a "Incremento F" (`board_service.py`, `docs/kanban.md`,
  ADR-0018). `required_role` não precisou de nenhuma mudança: `/approve` e
  `/rollback` já resolviam para admin por sufixo. 730 testes (39 novos),
  92%+ cobertura, validado em Docker/Postgres com o fluxo completo (risco
  baixo aceita automático, risco alto aguarda aprovação e reprova o gate até
  ser decidido, rollback cria o incidente).
- **Bateria de validações e escolha automática de esforço (ADR-0022):** fecha
  `fluxo.md` §12 e §9. `PUT /validation-checks` substitui o `validation_command`
  único por uma bateria nomeada (`ValidationCheck`: nome, comando, categoria,
  bloqueante), com cada comando validado por `validate_gate_command`;
  `validation_command` continua funcionando (inclusive na CI da PR) —
  `checks_efetivos` converte o legado numa verificação sintética `"testes"` sem
  mudar comportamento de nenhuma orquestração existente. `run_quality_gate` roda
  **um `Criterion` por verificação**, todos até o fim (sem parar no primeiro
  erro) — uma verificação `bloqueante: false` que falha vira aviso, não
  reprovação. `GET /validation-checks/suggest` sugere uma bateria determinística
  por stack (Python/Node/Go/Rust) sem gravar nada e sem inventar script
  inexistente. O roteamento de falha (ADR-0019) ganha `FailureRecord.check`/
  `categoria` e passa a preferir o fato à heurística: `formatacao`/`lint` →
  `falha_trivial` (nunca sobe effort); `seguranca`/`dependencias` → `risco_alto`
  (escala já na primeira falha); a escalada por reprovação de gate é gravada por
  FASE (`agent_assignments`), não por card isolado. `DemandBrief.complexidade`
  (coletada desde a ADR-0016 e nunca lida) passa a decidir o esforço efetivo via
  `sugerir_effort(complexidade, risco)` — penúltimo degrau da resolução, abaixo de
  toda escolha humana; cada resolução automática emite `EffortSugerido` no
  timeline. `ASO_EFFORT_AUTOMATICO=0` restaura o comportamento anterior. **Sem
  re-execução seletiva de checks** — decisão deliberada (§13 do fluxo.md: "não
  apenas o teste que falhou"). Dois vestígios fecham junto: `SPEC_KEY` importado
  (não mais literal solto) em `review.py`/`orchestration_service.py`; card
  `Cancelled`/`Archived` agora bloqueia o dependente com motivo explícito em vez
  de deixá-lo pendurado para sempre (`BoardService._refresh_dependents`).
- **Especificação e revisão documental (ADR-0021):** fecha `fluxo.md` §5/§6 — a
  ponta documental do runtime (demanda → ficha → discovery → **spec → revisão
  documental** → cards). `POST /spec/run` gera a especificação (o que será
  construído, fora de escopo, critérios de aceite, regras de negócio,
  componentes/alterações, estratégia de testes, plano de rollback,
  `itens_de_trabalho`) a partir do discovery **aprovado** (409 sem ele); fallback
  heurístico nunca falha e nunca sai `aprovado`. `POST /spec/review` roda a revisão
  documental (`ReviewService.revisar_documento`, quatro desfechos do §6 — não os
  cinco do §14): dois eixos são checados deterministicamente **antes de qualquer
  agente** — `estrategia_de_testes`/`plano_de_rollback` vazios reprovam sem gastar
  revisor. `ASO_MAX_RODADAS_DOC` (default 3) limita o ciclo reprovado→regenerado;
  esgotado, `necessita_humano` e só `POST /spec/approve` (admin) decide.
  Especificação aprovada materializa `itens_de_trabalho` em cards com dependências.
  `POST /run-phase` recusa (409) rodar F5 sem spec aprovada em `full-pipeline`
  **quando o discovery já está em uso** — não-regressivo para quem nunca chama
  `/discovery/run` (confirmado revertendo a checagem e vendo 9 testes
  pré-existentes falharem). Discovery e spec passam a ser **versionados** (ring de
  até 5, `control/documentos.py`) em vez de sobrescritos — `discovery_report`
  (dict) virou `discovery_reports`/`spec_documents` (listas), com migração de
  dados do formato antigo. `KanbanCard.closure` (§23) é preenchida no merge com o
  que o runtime tem à mão. `populate_from_plan` (backlog do LLM, caminho que
  `full-pipeline` usa de verdade) e os itens de trabalho da spec agora populam
  `dependencies`; `blocked_by` ganhou observador ativo (libera `Blocked → Ready`
  quando a última dependência chega a `Done`). `run_gate_command` corta
  `stdout`/`stderr` separadamente (antes colava e cortava, podendo perder o stack
  trace). O bloco `_perguntar`/`_rodar_cli`, duplicado em
  naming/triage/review/discovery, foi extraído para `control/agent_ask.py` antes
  de ganhar uma quinta e sexta cópia — refatoração pura, suíte dos quatro serviços
  existentes passou sem alteração.
- **Discovery e aprovação (ADR-0020):** `POST /discovery/run` roda o discovery
  (§3 do fluxo.md) — analisa o workspace (`WorkspaceAnalyzer`) e a ficha já triada,
  produz um `DiscoveryReport` (situação atual, problema, componentes afetados,
  riscos, alternativas, recomendação técnica, pontos de decisão); sem agente
  configurado (ou com falha), cai num resumo heurístico determinístico com
  `confianca: "baixa"` — nunca falha, mesmo princípio de `TriageService`
  (ADR-0016). `exige_aprovacao_discovery` (§4) decide entre aprovação automática e
  humana, reaproveitando o vocabulário de impactos sensíveis do motor de decisão;
  `POST /discovery/decide` (`{approved, comentario?}`) é ação crítica, exige
  `admin`, e segue o padrão auto-contido de `PullRequest.review_status`
  (ADR-0017) em vez do `HumanApproval` genérico. O gate de F1 passa a exigir
  `discovery_aprovado` **só quando um relatório foi de fato gerado** — dict vazio
  (discovery nunca rodado) não muda o comportamento de nenhuma orquestração
  existente, confirmado pela suíte completa (zero regressão) e por um roteiro
  manual em Postgres. `GET /discovery` traz o relatório atual; `next_step` ganha
  o item de checklist `discovery` (só em F1, quando já iniciado) e os bloqueios
  `discovery_reprovado`/`discovery_aguardando_aprovacao`. Sem migração de tabela —
  `discovery_report` é JSONB direto em `orchestrations`, mesmo padrão de
  `demand_brief`. Cobre só §3/§4 do fluxo.md; especificação e revisão documental
  (§5/§6) ficam para uma entrega seguinte.
- **Roteamento de falha (ADR-0019):** o §13 do `fluxo.md` deixa de ser letra morta —
  toda falha de execução é diagnosticada (`sem_permissao`/`timeout`/`teste_falhou`/
  `diff_vazio`/`agente_indisponivel`/`desconhecido`, `control/failure.py`, puro e
  determinístico) e roteada por uma política determinada: mesmo agente com nudge,
  effort maior, outro executor, bloquear, ou escalar para humano —
  `ASO_MAX_ESCALONAMENTOS` (default 3) é o limite duro. `POST /cards/{id}/run` tenta de
  novo internamente quando a decisão permite; `GET .../cards/{id}/failures` traz o
  histórico (ring de 5, novo `KanbanCard.failures`, JSONB); `POST .../cards/{id}/route`
  aciona o roteamento manualmente. `Failed` passa a significar só "a política escalou
  para humano" — CI reprovada agora vai para `NeedsFix` (corrigível), não `Failed`. O
  `retry()` global deixa de reexecutar tudo às cegas: gate reprovado roteia só os cards
  da fase que não chegaram a `Done`. `CardEvent` ganha `reason`/`result`/`evidence`/
  `next_action` (auditoria de movimentação do §8, pendência da ADR-0018 fechada aqui).
  Corrigido também um gate de risco contornável (ADR-0017): `report_review("approved")`
  exige justificativa mesmo com veredito aprovado quando o risco da demanda exige
  confirmação humana — antes o clique do agente bastava mesmo em risco alto.
- **Kanban fiel: colunas restantes + dependencies/blocked_by (ADR-0018):** três
  colunas novas — `Deploying`, `Validating` (selecionáveis via `POST /cards/{id}/move`
  genérico; sem gatilho automático, isso é trabalho do Incremento F) e `Cancelled`
  (novo `POST /cards/{id}/cancel`, espelhando `block`/`unblock`) — sem migration
  (`status` já era `String` puro). `KanbanCard.dependencies`/`blocked_by`, campos
  mortos desde sempre, passam a ser populados a partir de `PlannedAgent.depends_on` na
  criação e verificados em `POST /cards/{id}/run`: dependência pendente move o card
  para `Blocked` e recusa (`409`); nova tentativa depois que ela resolve executa
  normalmente. `docs/api.md` já afirmava (incorretamente) esse comportamento — passa a
  ser verdade. `run_plan` (execução multiagente automática) não é afetado — já ordenava
  por `depends_on` nas suas próprias ondas; a checagem nova vale só para `run_card`
  manual. Corrigidos de quebra `aso run` (CLI) e um teste de integração que rodavam
  cards manualmente sem respeitar ordem — passaram a usar `run_plan`.
- **Revisão independente de código (ADR-0017):** `report_review` deixa de gravar uma
  string sem checar quem revisou. `ReviewService` (`control/review.py`) roda um agente
  sobre o **diff real** de uma PR (`POST .../pulls/{pr}/review/run`) e produz um
  `ReviewVerdict` (aprovado/aprovado_com_sugestoes/alteracoes_obrigatorias/reprovado/
  necessita_humano, ações objetivas por severidade, pontos verificados); diferente de
  naming/triagem, o fallback de indisponibilidade é **sempre** `necessita_humano` —
  nunca aprova sozinho. O revisor é sempre diferente do executor que implementou o card
  (`KanbanCard.executor`, novo campo); `report_review("approved")` só aceita com
  veredito aprovado já registrado ou justificativa humana (papel admin). Risco alto ou
  impacto sensível na ficha da demanda (ADR-0016) impede a aprovação automática mesmo
  com o agente aprovando. Card reprovado vai para a nova coluna `NeedsFix` com as ações
  obrigatórias chegando ao agente na re-execução. `next_step` ganha os bloqueios
  `pr_review_nao_executada`/`pr_alteracoes_obrigatorias`/`pr_review_humana`; o antigo
  `pr_review_pendente` de um clique sem revisão não existe mais. Agente selecionável via
  `PUT/DELETE /v1/orchestrations/{id}/agents/revisao`. Corrigidos também dois pontos
  herdados da ADR-0016: a CLI (`aso run`) passa a triar a demanda como a API
  (`create_with_triage`, ponto único de entrada), e `POST .../brief` (re-triagem)
  recomputa o plano de execução enquanto nenhum card saiu de `Ready`.
- **Ficha da demanda / triagem (ADR-0016):** `POST /v1/orchestrations` agora tria a
  demanda antes de criar a orquestração — `TriageService` (`control/triage.py`)
  interpreta `user_request` numa `DemandBrief` (tipo, domínios, impactos, risco,
  complexidade, perguntas em aberto) que alimenta o `MultiAgentDecisionEngine`, hoje
  decidindo sempre sobre a constante `domains=["backend"]`/`risk_level=LOW`. Sem agente
  configurado (ou com falha), cai numa heurística determinística que preserva o
  comportamento atual. Agente selecionável via `PUT/DELETE
  /v1/orchestrations/{id}/agents/triagem` (mesmo mecanismo da ADR-0014); ficha
  persistida em `demand_brief` (JSONB) e exposta por `GET/POST
  /v1/orchestrations/{id}/brief`; `card.priority` passa a refletir o risco da ficha
  (antes sempre `MEDIUM`); `perguntas_abertas` aparece no "Próximo passo" sem travar a
  esteira. Painel "Ficha da demanda" na tela de detalhe.
- **Painel "o que o agente está fazendo" (ADR-0015):** a saída do agente CLI passa a ser
  lida **linha a linha enquanto ele trabalha** — `subprocess.run(capture_output=True)` só
  entregava os pipes depois que o processo morria, então a tela ficava parada por minutos.
  Novos `shared/agent_output.py` (porta: vocabulário + Protocols `OutputSink`/`OutputBus`),
  `observability/agent_log.py` (ring de 2 000 linhas por orquestração, cursor monotônico,
  thread-safe) e `GET /v1/orchestrations/{id}/agent-log?after={seq}`, lido por polling com
  cursor — o que dá replay ao recarregar a página no meio da execução. O log vive em
  memória e não sobrevive a restart da API (é telemetria; falha e motivo continuam no event
  log e no `block_reason`).
- **Feed interpretado do NDJSON (ADR-0015):** `execution/agent_stream.py`, função pura, traduz
  a saída em eventos legíveis — 💬 fala, 🔧 `Write src/app.js`, ✓ resultado. `claude -p`
  imprime só a resposta final, então `scripts/enable-agent-stream.sh` acrescenta
  `--output-format stream-json --verbose` aos perfis Claude e `--json` aos Codex (idempotente,
  com `--off`). O parser foi ajustado contra a **saída real** do Claude Code: `system` e
  `rate_limit_event` vazavam como JSON cru na tela, e o `thinking` é cortado curto para não
  empurrar as ações para fora do painel. Schema desconhecido degrada para "mostra como veio".
- **Esteira didática com agente por etapa (ADR-0015):** `PHASE_INFO` + `GET /v1/phases` dão
  nome, resumo e entrega de cada fase em pt-BR — "F1" sozinho não explicava nada. Cada etapa
  virou um cartão com chip de agente clicável (`PUT`/`DELETE .../agents/{key}`), tirando a
  escolha por etapa da ADR-0014 de dentro do modal de configuração.
- **Executor por etapa da esteira (ADR-0014):** `Orchestration.agent_assignments` (JSONB)
  guarda um executor por fase `F1..F7` e um para o nomeador, com `PUT`/`DELETE
  /v1/orchestrations/{id}/agents/{key}` e evento auditável `AgentAssignmentUpdated`. A
  resolução passa a ser: chamada explícita → etapa → padrão da orquestração → default do
  catálogo → provider global. Dá para rodar F1 com um modelo barato e F5 com o mais forte
  na mesma orquestração. Uma fase que já ficou para trás não aceita troca; o nomeador é
  sempre editável. Na tela de detalhe, o modal de configuração ganhou a matriz de agentes
  por etapa e a esteira mostra quem roda cada fase.
- **Nomes de branch derivados do card (ADR-0014):** novo módulo puro
  `execution/branch_naming.py`. As branches deixam de ser
  `aso/BackendDevelopmentAgent-claude-sonnet-medium-c6950ea8…` e passam a ser
  `feat/calculadora-basica-a1b2c3d4` — prefixo Conventional Commits pelo `CardType`, slug
  do título do card e sufixo curto de unicidade (necessário porque `retry` e candidatos
  concorrentes executam a mesma task). A mensagem do merge governado passa a citar branch
  e título em vez do `"aso: merge governado"` fixo.
- **Agente nomeador opcional (ADR-0014):** `control/naming.py` pode usar o executor de
  `agent_assignments["naming"]` para sugerir nome de branch e assunto de commit. Sem
  nomeador configurado (o padrão) não há chamada nenhuma. Qualquer falha — timeout, JSON
  inválido, exit ≠ 0, executor fora do catálogo — cai no nome determinístico e registra
  `NamingFallback`: nomear nunca derruba um card.
- **`scripts/reset.sh`:** zera o estado de runtime (volume do Postgres + schema recriado
  por Alembic, `aso.db` residual, worktrees órfãos via `git worktree remove`, `.aso/run`)
  preservando a governança versionada do próprio ASO e o catálogo de executores, que vive
  em arquivo. Lista os repositórios-alvo antes do drop e não os toca.

- **Tela de detalhe orientada a "próximo passo" (ADR-0013):** novo motor puro
  `control/next_step.py` (`compute_next_step`) que reúne, num único contrato, as regras de
  governança que travam a esteira — configuração (pasta, validação, executor, docs-first),
  pendências governadas (aprovação humana, CI/revisão/merge da PR, conflitos), trabalho da
  fase (cards bloqueados, falhos, em Ready ou Backlog, entrega sem PR) e sinais do gate,
  drift de docs e SLO. Cada bloqueio traz severidade, explicação e a rota que o destrava
  (com o papel exigido), e o de maior severidade vira a **ação primária**. Exposto em
  `GET /v1/orchestrations/{id}/next-step`. A rota `/ui/detalhe?id=…` passa a servir a nova
  `static/detalhe.html`, dedicada a **uma** orquestração (breadcrumb do projeto, esteira
  F1→F7, card "Próximo passo" com checklist, funil só da fase corrente, pendências
  acionáveis e atividade ao vivo por SSE) — sem o formulário de criação nem o kanban de 12
  colunas. O console técnico completo continua em `/ui/console`.
- **Drift-check contínuo de docs-first + self-heal (ADR-0012):** novo módulo
  determinístico `execution/docs_drift.py` (`check_drift` → módulos de código sem doc,
  docs órfãs, links internos quebrados e features ainda em placeholder). O quality gate de
  **F5/F6** ganha um critério **não-bloqueante** `docs_in_sync`: quando há drift, emite um
  **aviso** no `QualityGateResult` (a esteira segue, o snapshot é gerado). O **self-heal**
  (`POST /v1/orchestrations/{id}/docs-heal`) resolve em duas camadas — cria
  `docs/modules/<módulo>/` para módulos sem doc (determinístico) e, com executor real,
  preenche placeholders e conserta links num worktree isolado com o diff mesclado
  (governado) — registrando evento `DocsHealed` + `ContextPatch` `engineering.docs_drift`.
  Relatório em `GET /v1/orchestrations/{id}/docs-drift`; no console, indicador de drift e
  botão **"Sincronizar docs"**. **Self-heal automático no autopilot:** ao fim de F5/F6, o
  `run_phase` sincroniza a doc sozinho quando há drift (best-effort, retornado em
  `docs_autoheal`), desligável por `ASO_AUTOHEAL_DOCS=0`.
- **Executores Codex compatíveis (ADR-0011):** o catálogo gerenciado consulta
  `codex app-server`/`model/list`, cria `codex-default` sem modelo fixo e um perfil por
  modelo realmente disponível, com esforços suportados e versão do runtime. Nova
  sincronização administrativa e recuperação auditável de configurações/docs-first;
  retries que encontram apenas scaffold ASO parcial ou completo sem código completam ou
  reaproveitam deterministicamente o módulo `projeto` com as oito seções obrigatórias.
- **Catálogo multi-repo governado (ADR-0010):** `Project` e `ProjectEvent` agora usam
  persistência relacional por porta/adapters in-memory e SQLAlchemy. Paths são canônicos e
  únicos; `DELETE /v1/projects/{id}` arquiva sem cascata, restauração e arquivamento exigem
  `admin`, e o histórico expõe ator/estado anterior/posterior. A migração
  `f84c2a1d9e30` preserva IDs legados antes de criar FKs restritivas.
- **Pré-análise de workspace:** `GET /v1/fs/analyze/stream` enumera arquivos elegíveis
  em SSE, com progresso real e sem escrita. No console, a demanda de nova
  orquestração só é exibida após a pasta ser analisada com sucesso; trocar a pasta
  invalida essa liberação.

### Alterado
- **Console multi-repo:** `/ui/` administra projetos ativos/arquivados e agrupa o Kanban
  completo por projeto. `/ui/nova` executa projeto → pré-análise SSE → demanda/configuração
  → criação → docs-first → detalhe; não cria orquestração temporária nem inicia Autopilot.
  O Kanban removeu o seletor de executor por card que não tinha persistência.
- **Workspace vinculado:** criar orquestração com `project_id` exige projeto ativo e copia
  seu path; editar/arquivar o projeto não altera execuções existentes. A listagem aceita
  `project_id`; orquestrações sem projeto permanecem compatíveis.
- **Concorrência do catálogo:** updates relacionais validam o estado anterior e devolvem
  conflito em escrita obsoleta, evitando lost update entre processos.
- **Imagem Docker:** inclui Git, dependência operacional do scaffold docs-first e dos
  worktrees; ausência do binário é traduzida em erro de workspace governado.
- **Entrega de código governada:** falha CLI ou diff vazio agora bloqueia o card; para
  novas execuções com validação configurada, F5/F6 aguardam PR, CI real, revisão e
  merge no workspace da própria orquestração antes do gate.
- **Console:** o botão de pré-análise fica somente no card "Nova orquestração"; ele
  não é repetido no detalhe após a criação.
- **Governança (F5):** OrchestratorContext versionado, ContextBus (pipeline de 7 etapas), ADRRegistry, QualityGateEngine, SnapshotEngine, ConflictDetector.
- **Kanban:** board, cards e automação por eventos (§16.7).
- **Control:** MultiAgentDecisionEngine, ExecutionPlanner, OrchestrationService.
- **Agents:** AgentRegistry (16 agentes), ExecutionProvider + LocalMockExecutionProvider.
- **Interfaces:** API FastAPI v1, CLI Typer.
- **Persistência (ADR-0006):** repository ports + adapters in-memory e SQLAlchemy; tabelas normalizadas (§29) com tabelas de junção, índices e consultas; migrations Alembic (0001, 0002).
- **Qualidade/CI (F6):** pipeline GitHub Actions (ruff, mypy, pytest+cobertura≥80%, alembic check, bandit, pip-audit); Dockerfile; runbook e plano de deploy/rollback.
- **Camada de consulta (CQRS-lite):** consultas indexadas na porta e adapters; endpoints de leitura (`cards/stats`, `cards/by-status`, `adrs/by-status`, `adrs/{id}/linked-cards`) e comando `aso stats`.
- **Leituras (F7 read):** filtros de cards, timeline paginada, busca de ADRs; OpenAPI servido em `/`, `/docs`, `/openapi.json`; comandos `aso cards/adrs/timeline`.
- **Operação (F7):** `MetricsService` (métricas por orquestração e global), SLOs baseados em sintomas e regras de alerta (`/v1/metrics`, `/slo`, `aso metrics`); feedback→backlog (`POST /feedback`, `aso feedback`).
- **Gates/approvals persistidos + §28:** `QualityGateResult` e `HumanApproval` como entidades (migration 0003); endpoints de quality-gates, conflicts, approvals (aprovar/rejeitar) e ciclo de vida (rollback/cancel/resume); CLI `approvals`/`approve`/`rollback`.
- **Docker e2e:** `docker compose` (Postgres + API com migrations no boot e healthcheck `/health`), `scripts/smoke.sh` e job `smoke-docker` no CI. Correção de ordem de inserção por FK no adapter (compatível com o enforcement do Postgres).
- **Console web (SPA):** UI estática servida em `/ui` (dashboard, Kanban, timeline, ADRs, métricas) consumindo a API v1 — sem build Node.
- **Endpoints §28 restantes:** `retry`, `snapshots/{a}/diff/{b}`, `cards/{id}/assign-agent|move|block|unblock` + comandos CLI.
- **Normalização total:** `adr_options`, `gate_criteria` e `value_items` (listas planas) substituem colunas JSON; **PK composta `(orchestration_id, id)` em `adrs`** corrige colisão de ids sequenciais entre orquestrações. Validado no PostgreSQL.
- **Auditoria de patches:** `ContextPatch` persistido em `context_patches`; ContextBus registra toda submissão; endpoints `/patches`, `/audit` e `POST /context-patches`.
- **Console web (design system + telas):** abas de Kanban, ADRs, Approvals (aprovar/rejeitar), Snapshots (diff), Patches e Timeline sobre um mini design system.
- **Segurança — Auth/RBAC:** API key via `ASO_API_KEYS` (papéis viewer/operator/admin), middleware RBAC, endpoints críticos protegidos e ator registrado (`approved_by`). Públicos: `/health`, `/metrics`, `/`, `/ui`, `/docs`.
- **Observabilidade — Prometheus:** endpoint `GET /metrics` em formato de exposição Prometheus (`aso_orchestrations_total`, `aso_cards{status}`, `aso_open_conflicts_total`, ...).
- **Release:** `.github/workflows/release.yml` publica imagem versionada no GHCR por tag `vX.Y.Z`.
- **Gateway de observabilidade:** correlation-id `X-Request-ID` por request, **rate limiting** por IP (`ASO_RATE_LIMIT`), **logs JSON** (structlog) com `request_id`/`actor`, e **tracing OpenTelemetry** opcional (`ASO_OTEL=1`, extra `[otel]`).
- **Console:** login por token (Bearer, persistido) e aba de **auditoria** com resumo + filtro de patches por status.
- **Performance/escala:** listagem de orquestrações e métricas globais agora usam consultas diretas/agregadas (COUNT/GROUP BY) **sem hidratar** aggregates; paginação em `GET /v1/orchestrations` (`X-Total-Count`) e na timeline (`events_page`); índice em `orchestrations.created_at`; **cache de leitura TTL** (invalidado em escrita) no caminho quente de métricas.
- **MVP-2 — execução multiagente:** `run_plan` (`POST /run-plan`) executa os cards do plano na **ordem topológica** de `depends_on` (workers antes do ReviewAgent).
- **MVP-2 — fluxo de aprovação:** patch com `requires_approval` fica **PENDING** e gera uma `HumanApproval` vinculada; **aprovar aplica** o patch (`ContextBus.apply_approved`), rejeitar o mantém não aplicado. Ator autenticado registrado como `approved_by`.
- **Kanban ↔ aprovação:** card com patch pendente vai para **Waiting Human**; aprovar libera (Testing), rejeitar move para **Blocked**.
- **ConflictDetector avançado:** contradição com ADR aceita via `locked_paths` (override sancionado ao referenciar a ADR em `linked_adrs`) e proteção de contrato (remoção/alteração de versão). **ConflictResolutionAgent** (`POST /conflicts/{id}/resolve`) propõe resolução, escala o conflito e cria card `ADRTask`.
- **Execução concorrente + supervisão:** `run_plan` executa em **ondas topológicas** com agentes concorrentes (threads) e **escrita serializada** no ContextBus (single-writer); **AgentSupervisor** com retry+nudge; falha terminal move o card para **Failed**.
- **Auto-resolução:** patch rejeitado aciona o ConflictResolutionAgent automaticamente (escala + card `ADRTask`) e move o card para **Blocked**.
- **Console:** aba de **Conflitos** (listar/resolver) e **badge de aprovações pendentes**.
- **MVP-3 — provider CLI + worktrees:** `CliAgentExecutionProvider` roda o agente CLI (`claude`/`codex`/…) em **worktree/branch isolado por card**, coleta o **diff** e o devolve como ContextPatch; `WorktreeManager` (git worktree); seleção via `ASO_CLI_COMMAND` + `ASO_TARGET_REPO`.
- **Métricas de execução:** duração por execução (`AgentExecuted`), `GET /execution-metrics` (execuções, duração média, retries, falhas, waiting-human), counters `aso_agent_retries_total`/`aso_agent_failures_total` no `/metrics` e painel no console.
- **Console ao vivo (SSE):** `EventBroker` in-process + `GET /events/stream`; o gateway publica um tick por orquestração após cada mutação e o console (EventSource) atualiza kanban/timeline/métricas em tempo real (indicador "● ao vivo"; token via query param).
- **MVP-4 — PR/CI/Review:** `PullRequest` a partir do worktree do card (`open-pr`); `report_ci`/`report_review` realimentam o card (PR opened→Review, CI failed→Failed, changes→Review); o provider CLI faz commit na branch.
- **Merge governado:** `merge_pr` exige **CI `passed` + review `approved`** (§26A.6), faz **merge git real** na branch base (WorktreeManager), move o card para **Done**; endpoint `/merge` exige papel **admin**.
- **Candidatos CLI paralelos (§26A.6):** `CandidateRunner` executa múltiplos agentes CLI **em paralelo** por card, cada um em worktree/branch isolado (ThreadPoolExecutor; operações de metadados do git serializadas por `_GIT_META_LOCK`); coleta e **compara os diffs**, recomenda o **menor diff válido** e o expõe via `race_card` para abrir PR + merge governado. Falha de um candidato **não derruba** os demais.
- **Console — aba PRs:** aba **PRs** (`renderPulls`) e botão **"Abrir PR"** por card do Kanban; abrir PR, reportar CI/review e **merge** pela UI, com **merge bloqueado** sinalizado ao usuário.
- **Documentação de entrada:** `README.md` (visão, princípios de governança, arquitetura, começando com Docker/local, uso de CLI/API, qualidade, estrutura, roadmap) e `CLAUDE.md` (guia para agentes de IA: regras invioláveis de governança, fluxo de validação obrigatório por incremento, atualização de governança, convenções, armadilhas conhecidas). Ambos em pt-BR, com links relativos validados.
- **Corrida de candidatos via API + console:** `POST /v1/orchestrations/{id}/cards/{cid}/race` (papel **admin**) constrói os agentes CLI candidatos a partir do ambiente (`ASO_CANDIDATE_COMMANDS` + `ASO_TARGET_REPO`, via `build_candidate_providers`), roda a corrida em worktrees isolados e devolve a comparação de diffs (**409** quando nada configurado). No console: botão **"Candidatos"** por card, **painel de comparação** (executor · branch · diff · arquivos, com o recomendado destacado) e **"Abrir PR do recomendado"**.
- **Diff lado a lado + e2e da corrida:** o `CandidateRunner` passa a expor o **diff** de cada candidato (limitado a 20k caracteres) na comparação; o console renderiza os diffs em **colunas** com realce de `+`/`-`/hunks e a coluna recomendada destacada. Teste ponta a ponta via API (`test_candidates_e2e.py`) e script `scripts/e2e_candidates.sh` para exercitar agentes CLI reais.
- **Endurecimento de concorrência (revisão adversarial):** `OrchestratorContextStore.apply_patch` agora é **atômico** (RLock) — sob requisições paralelas na mesma orquestração não há perda de incremento nem duplicação de versão/histórico; `OrchestrationService` ganhou **lock por orquestração**, com `_bundle` em *double-checked locking* (instância única, sem *lost-update*) e `_persist` serializado; nomes de worktree/branch passam a incluir `executor_id` + id completo (evita colisão entre candidatos de mesmo papel); `collect_diff`/`commit` sob `_GIT_META_LOCK` (evita falha espúria de lockfile). Regressões em `test_concurrency.py`.
- **Corridas de candidatos rastreáveis:** nova entidade **`CandidateRun`** (candidatos + branch recomendado + timestamp) persistida na tabela **`candidate_runs`** (migração `9149277d0e97`); `race_card` grava a corrida e devolve `run_id`; endpoint **`GET /v1/orchestrations/{id}/candidate-runs`** (com filtro por `card_id`) expõe o histórico auditável.
- **Seleção manual de candidato:** cada coluna de diff no console ganha **"Abrir PR"** — é possível abrir PR de qualquer branch candidato, não apenas o recomendado (que segue destacado).
- **Atomicidade read-check-mutate:** o lock por orquestração passa a cobrir `merge_pr` (evita dupla-mescla) e `decide_approval` (evita aplicar o mesmo patch pendente em dobro); *stress test* multi-endpoint concorrente valida a consistência do estado após reidratação.
- **Console — histórico de corridas:** aba **"Corridas"** (`renderRaces`) consome `GET /candidate-runs` e reexibe candidatos e diffs de corridas anteriores, com o recomendado destacado e **"Abrir PR"** por candidato.
- **MVP-5 (F7) — timeline de custo por card:** o evento `AgentExecuted` passa a carregar `card_id`; `MetricsService.execution_timeline` agrega por card (execuções, tempo total/médio, falhas e detalhe por execução), aproximando o custo pelo tempo de execução. Endpoint **`GET /v1/orchestrations/{id}/execution-timeline`** + aba **"Custos"** no console (tabela + barras).
- **Retenção de corridas:** `ASO_MAX_RACES_PER_CARD` (default 20) poda corridas antigas por card, mantendo apenas as N mais recentes — evita o crescimento indefinido de `candidate_runs`.
- **MVP-5 (F7) — SLO error-budget + burn-rate:** o `/slo` ganha um SLI de **taxa de falhas de execução** com **orçamento de erro** (`ASO_SLO_FAILURE_BUDGET`, default 0.10), **burn-rate**, % consumido, **severidade** (ok/warning/critical) e **tendência** (rising/falling/stable); os SLOs de sintoma ganham severidade; a resposta inclui uma lista de **alertas por severidade** (medium/high). Aba **"SLO"** no console (barra de burn-rate, tabela de SLOs, alertas). Os campos `slos`/`breaches` foram mantidos para compatibilidade.
- **MVP-5 (F7) — série temporal de SLO + Prometheus:** nova entidade **`SloEvaluation`** persistida em `slo_evaluations` (migração `7a759f873114`); **`POST /v1/orchestrations/{id}/slo/evaluate`** registra uma amostra e **`GET .../slo-history`** devolve a série — com isso a **tendência do burn-rate passa a usar uma janela real** de amostras (fallback para a heurística de metades quando não há histórico). O `/metrics` Prometheus expõe **`aso_slo_burn_rate`** e **`aso_error_budget_consumed_pct`** rotulados por orquestração (scraping/alerta externo). Console: botão **"Avaliar agora"** + tabela de histórico de burn-rate.
- **Snapshots avançados (§23):** o `snapshot_diff` agora traz **`section_details`** (por seção alterada: chaves `added`/`removed`/`modified`) — diff semântico em vez de só "seções alteradas". Nova **restauração seletiva**: **`POST /v1/orchestrations/{id}/snapshots/{version}/restore-section`** (papel **admin**) restaura **apenas uma seção** a partir de um snapshot, registrada no histórico do contexto e acompanhada de uma **ADR de rastreabilidade** (espelha o protocolo de rollback, com efeito restrito). Console: detalhe de diff por seção + ação **"Restaurar seção"**.
- **Dry-run da restauração seletiva (§23):** **`GET .../snapshots/{version}/restore-section/preview?section=`** devolve o **delta semântico** (`added`/`removed`/`modified` + `no_op`) que a restauração aplicaria, **sem alterar** o contexto — o console **pré-visualiza o impacto** e exige confirmação antes da ação crítica (não aplica quando `no_op`).
- **Retenção de amostras de SLO:** `ASO_MAX_SLO_SAMPLES` (default 200) poda amostras antigas por orquestração, fechando o crescimento ilimitado de `slo_evaluations`.
- **Autopilot — cérebro LLM (M1, ADR-0007):** porta **`LlmClient`** injetável (stdlib `urllib`, sem dependência nova) com adapters **OpenAI-compatible (DeepSeek/OpenAI)** e **Anthropic**, `FakeLlmClient` para testes offline e `build_llm_client_from_env` (`ASO_LLM_*`). **`PromptBuilder`** monta o prompt (system+user) a partir do contexto exigindo saída JSON. **`LlmExecutionProvider`** executa um card via LLM e devolve um **`ContextPatch`** (o LLM nunca escreve o contexto direto).
- **Autopilot — planejamento por LLM (M2):** **`PlanningService`** transforma uma ideia num **`ProjectPlan`** validado (produto + ADRs + backlog); **`OrchestrationService.populate_from_plan`** materializa **cards e ADRs reais** no board sob governança; endpoint **`POST /v1/orchestrations/{id}/plan`** (cliente LLM injetável em `create_app`; **409** sem LLM configurado).
- **Autopilot — PhaseRunner (M3):** **`run_phase`** executa uma fase ponta a ponta (roda os cards Ready da fase → quality gate → snapshot) e, com o gate aprovado, **abre uma aprovação humana de avanço de fase** (`payload.kind = phase_gate`); **`advance_phase`** leva F1→…→F7 (**409** na última). Endpoints **`POST .../run-phase`** e **`POST .../advance-phase`**.
- **Autopilot — loop de auto-avanço (M4):** **`start_autopilot`** dá partida (roda a fase atual e abre a 1ª aprovação); ao **aprovar** uma aprovação `phase_gate`, o runtime **avança de fase e roda a próxima automaticamente**, que abre uma nova aprovação e **pausa ali** — ou seja, a esteira anda sozinha de F1 a F7 **pausando apenas nas aprovações humanas**; ao aprovar a última fase, a orquestração vira `completed`. Endpoint **`POST /v1/orchestrations/{id}/autopilot`** e botões **"▶ Autopilot"** / **"Rodar fase"** no console.
- **Autopilot — execução de código real + gate de testes (M5):** **`RoutingExecutionProvider`** roteia por fase (**LLM planeja** F1–F4, **agente CLI coda** F5–F6, com fallback para o único configurado); o `build_service` monta o roteador a partir de `ASO_LLM_*` + `ASO_CLI_COMMAND`/`ASO_TARGET_REPO`. O **quality gate das fases de código passa a rodar testes de verdade**: executa **`ASO_GATE_TEST_COMMAND`** no `ASO_TARGET_REPO` e **só aprova com a suíte verde** — testes vermelhos reprovam o gate e a fase **não avança**.
- **Seleção de executor por etapa (agente/modelo/esforço):** **`ExecutorCatalog`** (`ASO_EXECUTORS` em JSON + defaults do ambiente) permite escolher, por fase/autopilot, **qual agente** rodar (Claude CLI, Codex, DeepSeek, ou outro), com **modelo** e **esforço** (`low`/`medium`/`high`). Endpoint **`GET /v1/executors`**, parâmetros `executor`/`effort` em `/run-phase` e `/autopilot`, e **seletor no console**; a escolha é registrada na aprovação e **propaga no auto-avanço**. **Kill-switch (M6):** orquestração cancelada bloqueia novas execuções.
- **Tela de configurações de executores (⚙ Config):** o console ganhou uma tela para **criar/editar/remover** os perfis de agente (nome, tipo, provider, modelo, esforço, comando, env var da chave, default). Os perfis são persistidos por **`ExecutorSettingsStore`** em arquivo (`ASO_EXECUTORS_FILE`, default `.aso/executors.json`) — **apenas metadados; o valor da chave NUNCA é gravado** (a UI só exibe o *status* presente/ausente lendo a env var). Endpoints **`POST`/`DELETE /v1/executors`** exigem papel **admin**; o executor `mock` é protegido contra remoção.
- **Clareza (logs, estado e esteira):** a partir do diagnóstico "tudo confuso":
  - **Logs sem ruído** — o gateway não loga mais `/health`/`/metrics` e um filtro no
    `uvicorn.access` os oculta do access log; **eventos de domínio** passam a aparecer no
    stdout (`phase_completed`, `autopilot_advanced`/`autopilot_completed`, `agent_failed`
    como `warning` com o motivo, `pr_merged`).
  - **Estado visível na UI** — card em Failed/Blocked exibe o **motivo** (`block_reason`);
    botão desabilitado fica **cinza/não-clicável** (`.btn[disabled]`); o badge de SLO usa
    **rótulos amigáveis** ("SLOs em risco: cards bloqueados, snapshot ausente").
  - **Esteira coerente F1→F7** — a orquestração passa a **nascer em F1** (antes F5); um mapa
    papel→fase posiciona os cards na fase certa; o planejamento LLM distribui o backlog por
    F1–F7; e **fases sem cards não travam** o gate (aprovação vacua), então o autopilot
    percorre a esteira inteira.

- **Workspace por orquestração + documentação docs-first (ADR-0008):** ao criar uma
  orquestração agora se **seleciona uma pasta** (vazia ou com projeto) — `Orchestration.target_path`
  (migração `b3d1f0a24c7e`) **substitui o `ASO_TARGET_REPO` global só para aquela orquestração**
  (env vira *fallback*); `ExecutorCatalog.build(repo_override=…)` + o helper `_provider_for`
  atrelam os agentes CLI, o gate de testes e a corrida à pasta escolhida. Novo passo
  **"Analisar pasta"** (`POST .../analyze-folder`) gera/atualiza a documentação **docs-first**
  no padrão da skill `ai-docs-self-healing` (`docs/index.md` + `docs/modules/<módulo>/<feature>.md`,
  8 seções): **pasta vazia → scaffold determinístico** (sem agente); **projeto existente → o
  agente selecionado documenta em worktree isolado** com o diff mesclado (governado) — evento
  `WorkspaceAnalyzed` + `ContextPatch` `engineering.docs_first`. **`GET /v1/fs/dirs`** (navegador
  de pastas: só diretórios, nunca conteúdo). Console: **navegador de pastas (modal)**, **seletor
  de agente na criação** e botão **"Analisar pasta"** com status docs. Módulos novos
  `execution/workspace.py` e `execution/docs_scaffold.py`.
- **Seed de executores (`manager.sh seed`):** deixou de fixar modelos obsoletos e agora
  sincroniza somente as capacidades anunciadas pelo Codex efetivo. Perfis personalizados e
  Claude são preservados; modelo/esforço persistidos valem em docs, cards, fases e Autopilot.
- **`manager.sh` (operação local):** painel Bash em pt-BR para o modo híbrido — **Postgres
  no Docker** e **API local** na venv (serve `/ui`). `iniciar` sobe o banco, espera ficar
  saudável, aplica migrations e sobe o uvicorn em background; `parar`, `reiniciar`,
  `status`, `logs`, `db-logs`, `migrate`, `test`, `check`, `psql`, `shell` + menu
  interativo. Cria a venv e instala as dependências (incl. `psycopg`) se faltarem.
- **Wrapper de agente CLI:** `scripts/aso-agent-wrapper.sh` adapta a tarefa do ASO (JSON no
  stdin) em um prompt pt-BR e invoca o agente CLI (`codex exec`, `claude -p`, …) no worktree
  do card. Selecionar o executor no console o aplica a **todas as fases** (a escolha propaga
  pela cadeia de aprovações). README documenta a receita (Codex/Claude em F1→F7).

### Segurança
- SAST (bandit) e SCA (pip-audit) sem apontamentos.
- Secrets apenas via variáveis de ambiente; deny-by-default no ContextBus.

### Alterado
