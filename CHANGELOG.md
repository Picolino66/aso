# Changelog — ASO Runtime

Formato baseado em Keep a Changelog. Versionamento semântico.

## [0.1.0] — não lançado (MVP-1 + persistência)

### Corrigido
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
