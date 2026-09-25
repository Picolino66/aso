# ASO MEL Execution State

Checkpoint oficial da execução do backlog `MEL-*` (origem: [feedback.md](../feedback.md)).
Leia depois de [tasks/README.md](README.md). Código e Git prevalecem sobre este arquivo.

## Estado geral

* Última atualização: 2026-09-25
* Branch/base: `main`
* Commit base: `164c6ab` (nenhum commit feito por agente — regra 7)
* Task atual: MEL-55 (validando)
* Última task concluída: MEL-52
* Próxima task candidata: MEL-55 · MEL-06
* Estado: implementing

## Tasks concluídas

* MEL-10 — avanço de fase exige último gate PASSED da fase atual + `/advance-phase` admin.
  * Implementado: `OrchestrationService.advance_phase` busca o último `QualityGateResult`
    com `phase == current_phase` dentro de `_lock_for`; ausente/≠PASSED → evento
    `PhaseAdvanceRefused {phase, reason}`, `_persist`, `ValueError` (rota → 409).
    `_advance_after_phase_gate` captura a recusa (log `autopilot_advance_refused`) e para.
    `auth.required_role`: `/advance-phase` → admin.
  * Testes: `tests/unit/test_advance_phase_gate.py` (8): sem gate, FAILED, PASSED→FAILED,
    PASSED de outra fase, PASSED avança, autopilot avança, autopilot não arrasta com gate
    reprovado, rota 403 operator / 409 sem gate / 200 admin.
    Ajustados: `test_phase_runner`, `test_agent_assignments` (`_avancar`), `test_brief_api`.
  * Validação: ruff check OK · ruff format OK · mypy strict OK · alembic upgrade+check OK ·
    pytest 1364 passed / 93.45%. Docker não exigido (sem persistência/boot).
  * Governança: card MEL-10 (EPIC-12) no board, context (coverage/cards_done/increments),
    CHANGELOG, docs/quality-gates.md, docs/operations.md.
  * Achado: orquestração recém-criada tem cards em F5; o gate de F5 reprova sem output
    (`context_has_output`), então chegar a F7 exige `run_plan` antes — era mascarado pelo
    avanço livre. Comportamento correto; não é bug.

* MEL-11 — aprovação de estratégia pendente/rejeitada bloqueia execução; rejeição cancela.
  * Implementado: `OrchestrationService._recusar_se_estrategia_pendente(b)` (pendente →
    "aguardando aprovação humana"; última rejeitada → "rejeitada", fecha a burla via
    `resume`). Chamado em `run_card`, `run_plan`, `run_phase`, `race_card`,
    `start_autopilot` (antes de marcar running), `analyze_folder` e `heal_docs`.
    `decide_approval` com rejeição de `tipo="estrategia"` → `status=cancelled` + evento
    `StrategyRejected`. `next_step` já mostrava `aprovacao_pendente` (sem mudança).
  * Decisão: `heal_docs` também guardado (aciona agente real). discovery/spec/review/deploy
    NÃO guardados (fora da lista da task; não executam a estratégia).
  * Testes: `tests/unit/test_strategy_approval_guard.py` (12, provider contador).
    Ajustado: `test_governance_endpoints::test_gates_and_approvals_persist`.
  * Validação: ruff/format/mypy/alembic OK · pytest 1376 passed / 93.50%.
  * Governança: card MEL-11, context, CHANGELOG, docs/operations.md.

* MEL-12 — CI declarada restrita (ADR-0056): `passed` declarado exige admin (403) +
  justificativa (409) + evento `CIDeclared`; `PullRequest.ci_origem`
  (''/executada/declarada/desconhecida) persistido (migration `20755cca5b90`); ficha de
  encerramento mostra a origem.
  * Testes: `tests/integration/test_ci_declarada.py` (8); 8 testes-atalho com `JUST_CI`.
  * Validação: ruff/format/mypy OK · alembic up/down/up/check OK · pytest 1384 / 93.67% ·
    Docker/Postgres: /health 200, smoke OK, `alembic_version=20755cca5b90`, downgrade/upgrade
    no container OK.
  * Decisão: `merge_pr` não recusa CI declarada (declaração admin+justificativa é decisão
    humana legítima). `scripts/e2e_candidates.sh` já estava quebrado na aprovação de review
    sem justificativa (ADR-0017) — não corrigido (fora de escopo).

* MEL-15 — segurança por padrão (ADR-0057).
  * Implementado: `AuthService.from_env` fail-closed (sem chaves exige `ASO_DEV_MODE=1`);
    compose `127.0.0.1` + `POSTGRES_PASSWORD` + `ASO_DEV_MODE:-1` + `ASO_WORKSPACE_ROOTS:-/tmp`;
    `manager.sh` dev explícito em `127.0.0.1`; `required_role` admin para escrita em
    `validation-checks`/`deploy/config`/`deploy/pipeline`/`deploy/run`;
    `_exigir_admin_para_comando` (validation_command no corpo de criação/execution-settings);
    `workspace_roots()`/`WorkspaceRootError` em `validate`/`list_dirs` (resolve);
    `?token=` só em `/events/stream`; `/metrics` via `aggregate_metrics()["slo_latest"]`.
  * Testes: `tests/integration/test_seguranca_por_padrao.py` (20) + `tests/conftest.py` raiz.
  * Validação: ruff/format/mypy/alembic OK · pytest 1401 / 93.79% · Docker: health 200,
    smoke OK, portas 127.0.0.1, fs /etc 400, boot sem chaves e ASO_DEV_MODE=0 → RuntimeError,
    gauges SLO no Postgres OK.
  * Decisões: compose mantém dev mode ligado por padrão (local-only, explícito no arquivo);
    `/metrics` segue público; gauges SLO = última amostra persistida; `?token=` só
    `/events/stream` (nova.html usa EventSource em `/v1/fs/analyze/stream` sem token — já não
    funcionava com chaves; fica para MEL-55).

* MEL-13 — claim atômico de execução do card (ADR-0058).
  * Implementado: campos `em_execucao_desde`/`execution_id`/`execucao_dono` (migration
    `e4b1c8382290`); `_reivindicar_card`/`_liberar_claim`/`_recusar_se_em_execucao`;
    `run_card` (claim sob lock, provider fora, apply sob lock, retry mantém claim, release
    em finally); `run_plan` (claim por card, pula reivindicado); `race_card` (lease sem
    mover); `move_card_validado` recusa; `_recuperar_execucoes_interrompidas` em `_bundle`.
    `_apply_execution` não aplica mais `AgentStarted`.
  * Testes: `tests/integration/test_claim_de_execucao.py` (12).
  * Validação: ruff/format/mypy/alembic OK · pytest 1413 / 93.82% · Postgres: smoke OK,
    migration up/down/check, claim persistido + recuperação Failed persistida.
  * Decisões: claim (não a coluna) é a fonte de verdade; dono = instância do serviço
    (robusto a descarte de cache futuro; inválido para multiprocesso — MEL-56); recuperação
    preguiçosa na reidratação.

* MEL-14 — contrato do wrapper CLI (ADR-0059).
  * Implementado: `agents/contract.py` (TaskEnvelope v1, `ler_envelope`), `agents/render_prompt.py`
    (só stdlib; exit 2 em contrato inválido), wrapper `.sh` adaptador, envelope anexado em
    `_build_task`/`_docs_task`/`_docs_heal_task`/`agent_ask._rodar_cli` (formato antigo mantido),
    `agent_stream.extrair_resposta_final` antes de `parse_llm_json`.
  * Testes: `tests/unit/test_contrato_task_envelope.py` (20),
    `tests/integration/test_wrapper_cli_contrato.py` (8, wrapper real + CLI fake texto/stream).
  * Validação: ruff/format/mypy/alembic OK · pytest 1441 / 93.76% · bandit sem achado novo.
  * Decisões: `task_type` de pergunta é rótulo livre (existe `revisao_documental`); execução
    restrita a card|docs; erros de construção Pydantic viram `ContratoInvalido` em `ler_envelope`;
    sem `command_ask` (extrai do NDJSON).

* MEL-34 — suíte de invariantes de governança via API.
  * `tests/integration/test_governanca_invariantes.py` (27): regras 1–6, 9 e execução única;
    passo obrigatório no CI (`.github/workflows/ci.yml`).
  * Mutação: reverter MEL-10 gate/admin, MEL-11, MEL-12, MEL-13, MEL-15 → 1/1/1/2/1/4 falhas.
  * Validação: pytest 1468 / 93.75%; ruff/format/mypy/alembic OK.
* MEL-01 — `docs/GOVERNANCE.md` (9 regras → arquivo/função → teste → lacuna/MEL); CLAUDE.md,
  AGENTS.md e docs/index.md apontam para ele. Feita junto da MEL-34 (critério 3 dela).
  **Manter a tabela viva**: cada MEL que fecha lacuna atualiza a linha.

* MEL-16 — gate escopado por fase + `SKIPPED` (ADR-0060).
  * Implementado: `governance/gate_definitions.py` (definições declarativas + `tabela_markdown`),
    `GateStatus.SKIPPED` no engine, `run_quality_gate` monta `EstadoDoGate`, `advance_phase`
    aceita PASSED|SKIPPED, `run_phase(autopilot=True)` pula fases vazias (`PhaseSkipped`,
    `fases_puladas`), `next_step`, CLI por fase, console, `smoke.sh`.
  * Testes: `tests/unit/test_gate_por_fase.py` (19); ~77 testes revistos (fixtures de deploy
    com `validation_command="true"`, snapshots F2+F5, gate na fase do card, multifase).
  * Validação: ruff/format/mypy/alembic OK · pytest 1488 / 93.84% · Docker smoke OK.
  * Achado: aprovação `fase_gate` aprovada fora da fase corrente avança a fase corrente (payload
    `phase` não é conferido com `current_phase`) — ver DISCOVERED-04.

* MEL-17 — congelamento de snapshots, **Opção A** (ADR-0061).
  * Implementado: `SECOES_CONGELADAS_POR_FASE` aplicado no gate PASSED; override (ADR aceita)
    → `requires_approval` no bus → HumanApproval; `PlannedAdr.locked_paths`; snapshot da mesma
    versão substitui; `restaurar_ledger` (serviço/API/CLI) com alias `rollback`.
  * Testes: `tests/integration/test_congelamento_snapshot.py` (8); unit de override ajustado.
  * Validação: ruff/format/mypy/alembic OK · pytest 1496 / 93.87%.
  * Pendência futura: remover alias `rollback` (MEL-53).

* MEL-18 — docs-first e self-heal via entrega governada (ADR-0062).
  * Implementado: `_garantir_git` (flag `inicializar_git`), `_entregar_docs_por_pr` (card
    Documentation + PR), `_scaffold_em_branch`, `WorkspaceService.sem_historico`; commit direto só
    em pasta vazia + sem histórico; autoheal sem PR duplicada; `merge_pr` → `DocsMergeFailed`/
    `MergeFailed` + 409; `WorktreeManager.merge` aborta conflito; console confirma git init.
  * Testes: test_workspace_docs (11), test_docs_drift_flow e test_next_step_api revistos.
  * Validação: ruff/format/mypy/alembic OK · pytest 1500 / 94.12% · Docker smoke OK.

* MEL-19 — ContextBuilder (ADR-0063).
  * Implementado: `agents/context_builder.py`; `TaskEnvelope.contexto`; `PromptBuilder` e
    `render_prompt` renderizam o mesmo bloco; `_fontes_do_contexto`; `target_path` por card;
    `AgentExecuted.contexto_chars/contexto_omitidos`.
  * Testes: test_context_builder (6), test_contexto_injetado (4).
  * Validação: ruff/format/mypy/alembic OK · pytest 1510 / 94.15%.

* MEL-20 — bugs pontuais: `FASE_PADRAO_POR_PAPEL`; `run_plan` por card/dependências (+ guards
  kill-switch/orçamento, fecha DISCOVERED-01); título/critérios da demanda; `PlanningFailed` +
  blocker "Replanejar". Testes: test_bugs_pontuais_mel20 (17). pytest 1528 / 94.20%.

* MEL-02 — docs de núcleo alinhadas ao código (context, architecture, api, agents, index com
  63 ADRs, README, quality-gates/snapshots sem tabelas do processo de construção, agents/skills
  READMEs). pytest 1528 / 94.22%.

* MEL-03 — `contracts/openapi.json` gerado (`scripts/export-openapi.py`, ADR-0064) + teste de
  contrato; `openapi.yaml` removido (deleção só no working tree). pytest 1531 / 94.20%.
  **Ao mudar rotas: regenerar o contrato** (senão `test_openapi_contract` falha).

* MEL-05 — `docs/HOW_IT_WORKS.md` (glossário, diagrama, onde mexer, limites); links no README e
  índice. pytest 1531 / 94.20%.

* MEL-30 — `agent_runs` (ADR-0065): `AgentRun` + repositório memória/SQL (migration
  `accd40ad02c2`), gravação início/fim em `_execute_isolated`, decisão no mesmo run, perguntas via
  `contexto_de_run`, `run_id` = `execution_id` em eventos e `ASO_RUN_ID`, máscara de segredos,
  retenção, endpoints `/runs`. Testes: test_agent_runs (9). pytest 1540 / 94.25%; Postgres OK.
  Lacuna: `race_card` não gera AgentRun.

* MEL-32 — camada de aplicação + routers da API (ADR-0066), 13 passos com suíte verde a cada um.
  * Implementado: 20 serviços em `src/aso/application/` (bundles, queries, intake, classificacao,
    preparation, settings, agent_task, execution, candidates, cards, delivery, docs_first,
    workflow, recovery, approvals, qa, release, governanca, insights, catalogs), raiz de
    composição `composicao.py`, `delegacao.py::Delegado` (descritor tipado por ParamSpec);
    façade `control/orchestration_service.py` 7.834 → 466 linhas; `api/app.py` 2.756 → 170 com
    `api/routers/*.py` (11), `api/deps.py`, `api/schemas.py`; planejamento LLM fora do handler;
    27 mutadores passaram a persistir sob `with self._lock_for(...)`.
  * Testes: `tests/unit/test_camada_de_aplicacao.py` (sem import da façade, ≤800 linhas, app só
    compõe, paths do contrato nos routers, lock em todo `_persist`, RLock só no BundleStore),
    `test_bundle_store.py`, `test_query_service.py`. Ajustes de alvo (intenção igual):
    `test_claim_de_execucao` (monkeypatch em `svc._execution`), `test_bugs_pontuais_mel20`
    (`_phase_for_agent` de `application.intake`), `test_executor_settings`
    (`aso.application.catalogs.discover_codex`), `test_classificacao_e_recomendacao` (`_faixa`
    de `application.insights`), `test_cadastro_completo` (`svc._limites.orcamento_padrao_usd`).
  * Validação final: ruff/format OK · mypy strict OK (136) · alembic OK · pytest 1610 passed /
    94.79% · Docker/Postgres /health 200 + smoke OK · contrato OpenAPI idêntico.
  * Governança: card MEL-32 Done, context (coverage, cards_done, increments, module_map com
    `application`), CHANGELOG, ADR-0066 (passos 1–13), architecture.md, HOW_IT_WORKS.md,
    GOVERNANCE.md (seção de lock), CLAUDE.md/AGENTS.md (estrutura).
  * Observação para MEL-36: ciclo de pacote `control` (façade) → `application` → `control`
    (módulos de domínio: triage, failure, models…); módulo a módulo é acíclico. Resolver ao
    configurar o import-linter (ex.: mover a façade para fora de `control`).

* MEL-31 — execução assíncrona com fila persistida e workers (ADR-0067).
  * Implementado: ver checklist 31.1–31.5 abaixo (arquivado). Decisões: tabela `jobs` própria
    (não `agent_runs`), flag `ASO_EXECUCAO_ASSINCRONA` (código síncrono por padrão; Docker e
    manager ligados), `run_phase` roda os cards dentro do job (sem sub-jobs), cancelamento
    cooperativo com `JobCancelado(BaseException)`, só a aprovação humana agenda a próxima fase.
  * Validação: ruff/format OK · mypy strict OK (139) · alembic up/down/check OK · pytest 1632
    passed / 94.77% · Docker/Postgres: /health 200, smoke assíncrono OK (jobs `analyze_folder`
    e `run_card` done no Postgres), restart do container: `running` órfão → `failed`,
    `queued` → `done`.
  * Governança: card MEL-31 Done, context, CHANGELOG, ADR-0067, docs (operations, api,
    architecture, HOW_IT_WORKS, GOVERNANCE, index), OpenAPI regenerado.
  * Histórico do andamento:
    * ID: MEL-31 — execução assíncrona com fila persistida e workers (ADR-0067 a escrever)
    * Status: implementing — incrementos 31.1…31.6
    * Decisões: fila em tabela própria `jobs` (não em `agent_runs`: um job gera N AgentRun e tem
  parâmetros/resultado; ADR-0065 define agent_runs como registro por invocação de agente);
  endpoints `/v1/jobs/{id}`, `/v1/jobs/{id}/cancel`, `/v1/orchestrations/{id}/jobs`;
  flag `ASO_EXECUCAO_ASSINCRONA` (código: padrão desligado → suíte síncrona intacta;
  docker-compose/manager: ligado); `run_phase` roda os cards dentro do worker (sem sub-jobs,
  evita deadlock de pool; coordenação por onda fica para MEL-50); cancelamento cooperativo
  (ContextVar do job + registro do subprocess + `verificar_cancelamento()` entre passos).
    * Checklist:
  * [x] 31.1 `execution/jobs.py` (Job, InMemoryJobRepository, FilaDeJobs, cancelamento,
    recuperação no boot) + `JobRow`/`SqlAlchemyJobRepository` + migration `ffabdb4f1996` +
    `tests/unit/test_fila_de_jobs.py` (12)
  * [x] 31.2 `CliAgentExecutionProvider` registra o subprocess (`registrar_processo`); contexto
    copiado por tarefa nos ThreadPoolExecutor (`_execute_wave`, `CandidateRunner`);
    `verificar_cancelamento()` no topo do laço de tentativas do `run_card`, das ondas do
    `run_plan` e dos cards do `run_phase`; `JobCancelado(BaseException)` atravessa os
    `except Exception` por card
  * [x] 31.3 `api/execucao_assincrona.py` (handlers das 11 operações, `classificar_erro`),
    `api/routers/jobs.py` (`GET /v1/jobs/{id}`, `GET /v1/orchestrations/{id}/jobs`,
    `POST /v1/jobs/{id}/cancel` — operator), `ApiDeps.fila/enfileirar` (202), `create_app(
    execucao_assincrona=, job_repository=)` + lifespan (boot recupera/sobe workers),
    `bootstrap.build_job_repository`; rotas 202: cards/run, race, run-plan, run-phase,
    autopilot, discovery/run, spec/run, spec/review, pulls/review/run, analyze-folder,
    docs-heal; OpenAPI regenerado. Testes: `tests/integration/test_execucao_assincrona.py` (8)
    + race assíncrona em `test_candidates_api.py`
  * [x] 31.4 `WorkflowService.definir_agendador_de_fase` (façade delega); aprovação de
    `fase_gate` (`_advance_after_phase_gate(agendar=True)`) enfileira `run_phase` com
    `autopilot=True` + evento `PhaseScheduled`; pular fases vazias continua no mesmo job
  * [x] 31.5 `static/jobs.js` (`asoAguardarJob`/`asoResolverResposta`, evento `aso:job`) incluído
    em index, nova, detalhe, card-detalhe, demanda-detalhe, demanda-nova (helpers `api` tratam
    202; JS verificado com `node --check`); `smoke.sh` com `executar` (202 → polling) + passo 8
    (fila); docker-compose `ASO_EXECUCAO_ASSINCRONA:-1`, `ASO_WORKERS:-2`; manager.sh liga a flag
  * [ ] 31.6 ADR-0067, docs, governança, bateria + Docker


* MEL-33 — persistência incremental, versão otimista e cache com descarte (ADR-0068).
  * Validação: ruff/format OK · mypy strict OK (140) · alembic up/down/check OK · pytest 1643
    passed, 7 skipped (variantes Postgres sem env) / 94.76% · Postgres do compose: 18 testes de
    persistência (create_all) e 26 (persistência + assíncrona) no schema migrado; Docker smoke
    OK; downgrade/upgrade no container e mutação da orquestração migrada OK.
  * Governança: card MEL-33 Done, context, CHANGELOG, ADR-0068, docs (operations,
    architecture, GOVERNANCE, index), CLAUDE.md/AGENTS.md.
  * Histórico do andamento:
    * ID: MEL-33 — persistência incremental, versão otimista e cache com descarte (ADR-0068)
    * Desenho: `save` calcula unidades por tabela a partir do estado (entidades com PK → merge;
  grupos de junção por dono → delete do grupo + insert; sequências `events`/`context_history`
  → só a cauda nova, removendo sufixo se o prefixo mudou) e compara com impressões (hash)
  guardadas pelo repositório por orquestração+versão (montadas no `load`/`save`; se faltarem,
  recalcula do banco). Inserts por nível de FK, deletes em ordem reversa.
  `orchestrations.versao`: `UPDATE ... WHERE versao = esperada` (0 linhas → 
  `ConcurrentModificationError`, 409 na API e no job); `save` devolve a nova versão;
  `OrchestrationState.versao` e `OrchestrationBundle.versao`. BundleStore: conflito descarta o
  bundle do cache; cache LRU (`ASO_BUNDLE_CACHE_MAX`, padrão 128, não descarta bundle com lock
  ocupado); sonda de versão no `get` (`ASO_BUNDLE_VERIFICACAO_S`, padrão 1 s, só com lock
  livre). `bootstrap` com `create_schema=False`.
    * Checklist: [x] 33.1 `db/gravacao.py` (unidades/impressões), `save` incremental + `versao_atual`,
  `ConcurrentModificationError` (ports), memória com versão, BundleStore guarda `versao` e
  descarta bundle em conflito, API 409 (`exception_handler`) e job 409; migration
  `813ddb006951` (`orchestrations.versao` com backfill 1; `posicao` em 13 tabelas; leitura
  ordena por `posicao`) · [x] 33.2 `CacheDeBundles` LRU thread-safe (não descarta o recém-
  inserido nem bundle com lock ocupado) + sonda de versão no `get` · [x] 33.3 bootstrap com
  `create_schema=False` · [ ] 33.4 ADR-0068, docs, bateria, Docker smoke, governança.
  Testes: `tests/integration/test_persistencia_incremental.py` (11 SQLite + 7 Postgres via
  `ASO_TEST_POSTGRES_URL`; 18 passed no Postgres do compose). Ajuste: test_camada_de_aplicacao
  permite `app.exception_handler`.


* MEL-40 — discovery e revisão com leitura do repositório (ADR-0069).
  * Validação: ruff/format OK · mypy strict OK (141) · alembic OK · pytest 1654 passed, 7 skipped
    / 94.77%. Docker não exigido (sem persistência/boot).
  * Pendência registrada: flag `--permission-mode plan` do Claude Code não exercitada contra o
    binário real (testes com CLI fake); a verificação pós-pergunta cobre a falha.
  * Governança: card MEL-40 Done, context, CHANGELOG, ADR-0069, docs.
  * Histórico do andamento:
    * ID: MEL-40 — discovery e revisão com leitura do repositório (ADR-0069)
    * Desenho: `execution/repositorio_leitura.py` (worktree destacado temporário do ref, flags de
  somente leitura por CLI — Codex `--sandbox read-only`, Claude `--permission-mode plan` (a
  confirmar contra o binário real) —, verificação `git status`/HEAD após a pergunta →
  `EscritaNoRepositorio` descarta a resposta); `perguntar_ao_agente(repositorio=)` + evento
  `PerguntaDescartadaPorEscrita` via `ContextoDeRun.ao_evento`; discovery com `evidencias`
  (arquivo precisa existir), `acesso_repo`, saneamento remove componentes inexistentes; revisão
  recebe item de spec, critérios, ADRs e saída da última CI, lendo a branch da PR. LLM: sem
  acesso (`acesso_repo=false`).
    * Feito (código+testes): `execution/repositorio_leitura.py`; `agent_ask` (`repositorio=`,
  `tem_acesso_ao_repositorio`, `ContextoDeRun.ao_evento`, `envelope.acesso_repo` no AgentRun);
  discovery (`_DISCOVERY_COM_REPOSITORIO`, `EvidenciaDoDiscovery`, `acesso_repo`,
  `componentes_descartados`, saneamento com repositório); preparation passa a pasta; review
  (`system_de_revisao`, `_pedido` com spec/ADRs/CI, `repositorio`); delivery passa fontes do
  ContextBuilder, `_ultima_saida_de_ci` e a branch da PR. Testes:
  `tests/unit/test_repositorio_leitura.py` (8), `tests/integration/test_perguntas_com_repositorio.py` (3).
    * Falta: bateria completa, ADR-0069, docs (GOVERNANCE regra 5, operations/agents), governança.


* MEL-41 — uso e custo para todos os executores (ADR-0070).
  * Validação: ruff/format OK · mypy strict OK (142) · alembic OK · pytest 1668 passed,
    7 skipped / 94.76%. Docker não exigido (sem persistência/boot).
  * Pendência registrada: schema do Codex confirmado só nas strings do binário 0.144.6 (sem
    execução real, para não gastar a conta do operador).
  * Governança: card MEL-41 Done, context, CHANGELOG, ADR-0070, docs.
  * Histórico do andamento:
    * ID: MEL-41 — uso e custo para todos os executores (ADR-0070, atualiza ADR-0026)
    * Desenho: origens de uso `agente` (CLI informou custo) · `tabela` (custo calculado por
  `ASO_PRECOS_MODELOS`) · `tokens` (tokens sem preço → custo indisponível) · `indisponivel`;
  `execution/precos.py`; clientes LLM ganham `completar() -> RespostaLlm(texto, uso)` (`complete`
  segue devolvendo texto — compatibilidade); `LlmExecutionProvider` grava `artifacts["uso"]`;
  Codex `turn.completed.usage` (campos confirmados nas strings do binário 0.144.6, sem chamada
  real); CLI provider recebe o `modelo` do perfil; `perguntar_ao_agente` grava uso no AgentRun;
  orçamento soma card + custo das perguntas (`AgentRunRepository.custo_de_perguntas`, fonte
  única em `agent_runs`); aprendizado ganha `proporcao_sem_custo` por executor.
    * Feito (código+testes): `shared/agent_usage.py` (origens), `execution/precos.py`,
  `llm_client.py` (`RespostaLlm`, `completar`, `uso_openai`, `uso_anthropic`, Fake com `uso`),
  `llm_provider.py` (`artifacts.uso`), `agent_stream._uso_codex`, CLI provider/catálogo com
  `modelo`, `_uso_do_output` precifica, `agent_ask` grava uso no AgentRun,
  `custo_de_perguntas` (memória e SQL), `_gasto_usd` soma perguntas, aprendizado
  `proporcao_sem_custo` + console. Testes: `tests/unit/test_uso_e_precos.py` (9),
  `tests/integration/test_custo_todos_executores.py` (5).
    * Falta: bateria, ADR-0070, docs (operations orçamento/preços), governança.


* MEL-36 — regra de dependência verificada (import-linter).
  * Validação: ruff/format OK · mypy strict OK · lint-imports 1 kept (mutação quebra) · alembic
    OK · pytest 1679 passed, 7 skipped / 94.75% · Docker /health 200 + smoke OK.
  * Atenção para próximos agentes: a façade agora é `aso.application.orchestration_service`
    (não existe mais `aso.control.orchestration_service`); tasks/feedback antigos citam o caminho
    velho.
  * Histórico do andamento:
    * ID: MEL-36 — regra de dependência verificada (import-linter)
    * Grafo medido (AST): ciclos `application`↔`control` (façade em control), `control`↔`observability`
  (`metrics.py` importa a façade) e `control`↔`persistence` (serviços de catálogo em control
  usam portas de persistence, que usam modelos de control).
    * Desenho: façade vai para `aso/application/orchestration_service.py` (sem shim — o shim manteria o
  ciclo; imports atualizados em src/tests/scripts/docs); `project_service`, `routing_rule_service` e
  `agent_catalog_service` vão para `application/`; `MetricsService` recebe porta
  `FonteDeMetricas` (Protocol em observability). Camadas: api|cli → bootstrap → db → application →
  persistence → control → execution → agents → governance|kanban|observability → shared.
  `import-linter` no extra dev + contrato em pyproject + passo no CI antes dos testes; teste AST sem
  dependência garante ausência de ciclos na bateria normal.


* MEL-35 — retry único via roteamento de falha (ADR-0071).
  * Validação: ruff/format OK · mypy OK · lint-imports OK · alembic up/down/check OK · pytest
    1681 passed, 7 skipped / 94.73% · Docker /health 200 + smoke OK.
  * Histórico do andamento:
    * ID: MEL-35 — retry único via roteamento de falha (atualiza ADR-0019 → ADR-0071)
    * Desenho: `AgentSupervisor(max_attempts=1)` por padrão e relança o erro ORIGINAL (sem prefixo
  "falhou após N tentativas"); nomeação calculada uma vez por card e guardada em
  `KanbanCard.branch_stem`/`commit_subject` (colunas novas em `kanban_cards`, migration);
  testes que dependiam das 2 tentativas internas ajustados mantendo a intenção.
    * Feito: supervisor 1 tentativa (AgentExecutionError com mensagem original encadeada); evento
  `AgentRetry` emitido pelo laço do `run_card` a cada decisão de nova tentativa (métrica mantida);
  `AgentTaskService._nomes_do_card` + `KanbanCard.branch_stem/commit_subject` + migration
  `84f292331b7a`. Testes ajustados (intenção preservada): test_agent_log_api (4→2 sessões),
  test_execution_metrics (2 execuções, 1 falha registrada), test_failure_routing_api (4→2
  arquivos), test_supervisor_concurrency (retry pelo roteamento), test_tentativas_historico
  (contador do script). Novos: `test_uma_chamada_ao_provider_por_decisao_do_roteamento`,
  `test_agente_de_nomeacao_e_chamado_no_maximo_uma_vez_por_card`.
    * Falta: bateria, ADR-0071, docs, Docker (coluna nova), governança.


* MEL-42 — structured outputs com JSON Schema (ADR-0072).
  * Validação: ruff/format OK · mypy OK · lint-imports OK · alembic OK · pytest 1705 passed,
    7 skipped / 94.88%. Docker não exigido.
  * Pendência registrada: parâmetros nativos de saída estruturada não exercitados contra APIs reais.
  * Histórico do andamento:
    * ID: MEL-42 — structured outputs com JSON Schema (ADR-0072)
    * Desenho: modelo `Resposta*` por função de agente (nomeação, triagem, discovery, spec, revisão,
  revisão documental, planejamento) ao lado do prompt; vocabulário fechado como `enum` no schema
  (campo `str` + `json_schema_extra`, a regra continua no `_sanear` — sem mudar fallback);
  `control/respostas_estruturadas.py` (instrução de formato gerada do schema, validação com
  caminho do campo, mensagem de correção); `perguntar_ao_agente(modelo_resposta=)` valida e faz
  no máximo UMA correção; envelope leva `output_schema`; prompts sem JSON escrito à mão; adapters:
  OpenAI `response_format json_schema` (DeepSeek `json_object`), Anthropic tool use forçado.
    * Feito: `control/respostas_estruturadas.py`; `agent_ask` (validação + 1 correção, schema no
  envelope e no system legado); modelos `RespostaNomeacao`, `RespostaTriagem`,
  `RespostaDiscovery`, `RespostaEspecificacao`, `RespostaRevisao`, `RespostaRevisaoDocumental` (+
  `ProjectPlan` no planejamento); prompts sem JSON manual; `llm_client` com saída estruturada
  nativa (`ASO_LLM_SAIDA_ESTRUTURADA=0` desliga). Testes: `tests/unit/test_respostas_estruturadas.py`
  (24) + snapshots `tests/snapshots/schemas/*.json`; ajuste em test_review_service (mensagem com o
  campo faltante).
    * Falta: bateria, ADR-0072, docs, governança.


* MEL-43 — effort mapeado por executor (ADR-0073).
  * Validação: ruff/format OK · mypy OK · lint-imports OK · alembic up/down/check OK · pytest
    1724 passed, 7 skipped / 94.93% · Docker /health 200 + smoke OK.
  * Histórico do andamento:
    * ID: MEL-43 — effort mapeado por tipo de executor (ADR-0073, atualiza ADR-0022)
    * Evidência offline: `claude --help` (2.1.215) tem `--effort <low|medium|high|xhigh|max>` e
  `--permission-mode` aceita `plan` (confirma MEL-40); Codex segue `-c model_reasoning_effort`.
    * Desenho: `execution/effort.py` (`suporte_de_effort(perfil)` e aplicação: Codex flag; Claude CLI
  `--effort`; OpenAI modelos de raciocínio `reasoning_effort`; Anthropic modelos com thinking
  `thinking.budget_tokens` — não junto com ferramenta forçada; DeepSeek/mock/CLI desconhecido: sem
  suporte); `public()` com `suporta_effort`/`effort_como`; `decidir` pula `aumentar_effort` para
  perfil sem suporte; `agent_runs.effort_aplicado` (migration); console avisa quando não há efeito.
  Envelope mantém `effort: str` (Codex/Claude aceitam níveis além de low|medium|high).
    * Feito: `execution/effort.py`; catálogo (`suporte_de_effort`, `public().suporta_effort/effort_como`,
  `cli_command` com `aplicar_effort_no_comando`, clientes LLM recebem effort); OpenAI
  `reasoning_effort`, Anthropic `thinking` (+ parse do bloco `text`); `failure.decidir` pula
  aumentar_effort sem suporte; providers `aplica_effort`; `AgentRun.effort_aplicado` + migration
  `88bb8b412a7f`; console (nova, index, detalhe). Testes `tests/unit/test_effort_por_executor.py`
  (18) + `test_failure_routing` (catálogo com CLIs que aplicam esforço + teste de pulo).
    * Falta: bateria, ADR-0073, docs, Docker (coluna nova), governança.


* MEL-51 — lock git por repositório.
  * Validação: ruff/format OK · mypy OK · lint-imports OK · alembic OK · pytest 1728 passed,
    7 skipped / 94.93%; mutação (lock global) derruba 2 testes. Sem ADR (task não exige).
  * Histórico do andamento:
    * ID: MEL-51 — lock git por repositório
    * Desenho: `lock_do_repositorio(caminho)` (registro `dict[str, Lock]` por caminho resolvido, sob um
  lock de registro) substitui `_GIT_META_LOCK`; escritas (`worktree add/remove/prune`, `add`,
  `commit`, `merge`, `collect_diff`) seguem sob o lock do repositório; leituras puras
  (`branch_diff`, `changed_files`, `commit_count`, `line_stats`, `list_worktrees`) sem lock;
  `repositorio_leitura` usa o lock do repositório. Teste de sobreposição com dois repositórios.


* MEL-50 — paralelismo por onda (ADR-0074).
  * Validação: ruff/format OK · mypy OK · lint-imports OK · alembic OK · pytest 1734 passed,
    7 skipped / 94.82%. Docker não exigido.
  * Histórico do andamento:
    * ID: MEL-50 — paralelismo por onda (ADR-0074)
    * Desenho: `application/ondas.py::CoordenadorDeOndas` — onda = cards Ready cuja dependência está
  `Done`; executa por `run_card` (claim, retry, guards) em ThreadPool com limite por orquestração
  (`ASO_MAX_PARALELO_POR_ORQUESTRACAO`, padrão 2; estratégia `parallel_agents` usa o limite, as
  demais 1) e semáforo global (`ASO_MAX_EXECUCOES_SIMULTANEAS`, padrão 4); card com dependência
  pendente não entra (fica `aguardando_dependencia`); `run_phase` e `run_plan` usam o mesmo
  coordenador (run_plan deixa de ter laço próprio com `_execute_wave`).
    * Feito: `application/ondas.py`; workflow `run_phase`/`run_plan` via coordenador (+ evento
  `CardsAguardandoDependencia`, resultado com `paralelismo`/`aguardando_dependencia`). Testes novos
  `tests/integration/test_paralelismo_por_onda.py` (4); ajustados à regra "dependência só depois de
  Done": test_mvp2, test_supervisor_concurrency, test_bugs_pontuais_mel20.
    * Falta: bateria, ADR-0074, docs, governança.

* MEL-53 — remoção de código morto (ADR-0075).
  * Validação: ruff/format OK · mypy OK · lint-imports OK · alembic up/down/check OK · pytest
    1734 passed, 7 skipped / 94.77% · Docker: smoke OK, migration converteu estratégia antiga e
    removeu colunas; API lê o plano migrado.
  * Histórico do andamento:
    * ID: MEL-53 — remover código morto e abstrações vazias (ADR-0075)
    * Decisões por item (evidência medida em 2026-09-15): AgentExecutor, `_agent_order`, passos vazios
  do ContextBus → remover; `ExecutionStrategy` → só `single_agent`/`sequential_agents`/
  `parallel_agents` (MEL-50: são as que mudam execução; `evaluator_optimizer` e `supervisor_worker`
  viram `sequential_agents` com o motivo preservado; migration de dados); `PlannedAgent.parallel_group`/
  `allowed_tools` e `AgentSpec.allowed_tools`/`requires_approval_for` → remover (migration);
  campos só persistidos de `AgentDefinition` → marcados informativos na UI/modelo; papéis sem card
  → `reservado` (ConflictResolutionAgent RECEBE card ADRTask: fica ativo, a evidência da task está
  desatualizada); `ConflictType` nunca levantados → remover; card do ReviewAgent → deixar de criar;
  congelamento (MEL-17) → mantido; `recover_invalid_execution`/`_LEGACY_CODEX_NAMES` → mantidos com
  data de remoção.
    * Checklist: [x] 53.1 executor/_agent_order/passos vazios (docs 6 etapas) · [x] 53.2 estratégias
  (migration `c3986f6a1a5d` com mapa de dados) · [x] 53.3 campos de plano/agente · [x] 53.4
  ConflictType, papéis reservados (`AgentSpec.reservado`, GET `/v1/agent-definitions/roles/reservados`,
  OpenAPI regenerado), AgentDefinition informativo (UI) · [ ] 53.5 card do ReviewAgent (em curso:
  decision_engine não cria mais; ajustar testes) · [ ] 53.6 datas de remoção, ADR, docs, governança


* MEL-54 — catálogo único de executores (ADR-0076; atualiza ADR-0007/0011/0014, adendo em 0069).
  * Implementado: `execution/flags_de_cli.py` (`familia_do_comando`, `aplicar_flags`,
    `migrar_comando`) monta streaming/permissão por família (Claude `--output-format stream-json
    --verbose`, `--permission-mode plan|acceptEdits`, `--dangerously-skip-permissions`; Codex
    `--json`, `--sandbox read-only|workspace-write|danger-full-access`); `ExecutorProfile` ganha
    `streaming`, `permissao_escrita`, `candidato` + validator que migra flags do comando
    (idempotente) e `public()` expõe `familia_cli`; `ExecutorSettingsStore.load` migra, regrava e
    guarda `.aso/executors.json.antes-adr-0076`; `migrar_perfis_salvos` põe `ASO_LLM_API_KEY` em
    perfil LLM sem `api_key_env` (a reserva global saiu de `llm_client`/`public`);
    `build_catalog_from_env` é o único leitor de env (candidatos viram perfis `candidato`, CLI
    antes do LLM vira padrão); bootstrap sem provider global, `execution/routing_provider.py` e
    `build_llm_client_from_env` removidos; `PLANNING_KEY` + `cliente_de_planejamento` (etapa →
    LLM padrão com chave) e `candidatos_da_corrida` (lista do corpo → perfis `candidato`, só CLI)
    em `ExecutionSettingsService`, com rotas `/plan`, criação full-pipeline e `.../race` (RaceBody)
    traduzindo para 409; `comando_somente_leitura` tira flags de autonomia total; console ⚙ Config
    com os campos + coluna CLI e etapa Planejamento no detalhe; `enable-agent-stream.sh` e
    `fix-executor-permissions.sh` apagados.
  * Testes: `tests/integration/test_catalogo_unico_executores.py` (25). Negativos/governança:
    `test_pergunta_somente_leitura_anula_permissao_total`, `test_permissao_invalida_e_recusada`,
    `test_corrida_recusa_candidato_invalido`,
    `test_etapa_de_planejamento_recusa_executor_que_nao_e_llm`,
    `test_nenhuma_leitura_de_executor_por_ambiente_fora_do_seed` +
    `test_varredura_pega_leitura_nova_fora_do_seed` (mutação que prova a varredura),
    `test_store_migra_arquivo_antigo_sem_perda_e_so_uma_vez`. Ajustados:
    `test_m5_code_execution` (sem os 3 testes do RoutingExecutionProvider),
    `test_candidates_api`/`test_candidates_e2e` (perfis do catálogo),
    `test_executor_catalog_codex` (sandbox virou campo); `tests/conftest.py` isola
    `ASO_EXECUTORS_FILE` (a leitura regrava o arquivo e não pode tocar o do operador).
  * Validação: ruff check/format OK · mypy strict OK · lint-imports KEPT · alembic upgrade+check OK
    (sem migration: nada de schema) · pytest 1756 passed / 7 skipped / 94.83% · Docker/Postgres:
    /health 200, smoke OK, catálogo semeado migrou a flag do comando no container, `/plan` e
    criação full-pipeline em 409 apontando o catálogo, corrida sem lista usou o perfil `candidato`
    (job `done`; erro esperado "No such file or directory: claude" — binário ausente no container).
  * Fato de campo: o `.aso/executors.json` real do operador foi migrado (16 perfis) — comando
    pronto idêntico token a token ao anterior; backup em `.aso/executors.json.antes-adr-0076`
    (ignorado pelo git).
  * Decisões: `total` do Claude usa `--dangerously-skip-permissions` (flag que os perfis já usavam
    e que o diagnóstico `sem_permissao` reconhece), não `bypassPermissions`; seed **não** é
    persistido no primeiro boot (ambiente efêmero continua configurável); valor sem campo
    equivalente (`--permission-mode auto`) fica no comando.

* MEL-44 — índice estrutural do repositório por commit (ADR-0077).
  * Implementado: `execution/code_index.py` — `IndiceDoRepositorio` por `(repo, commit)` com
    linguagem/linhas, símbolos públicos com linha, imports resolvidos para caminhos do repo,
    marcação de teste e entradas HTTP/CLI; Python por `ast` (métodos como `Classe.metodo`,
    imports relativos, raízes `src/lib/app`, rotas de decorador inclusive dentro de fábricas),
    TS/JS por regex com `precisao` declarada, outras linguagens só no inventário. Consultas
    `vizinhanca`/`testes_que_cobrem` (diretos antes dos indiretos)/`quem_importa`/`contem`/
    `resumo`. Cache em `.aso/index/<commit>.json` + 60 s no processo (`indice_para_uso`);
    árvore suja recalcula sem gravar; `.aso/` não conta como sujeira (senão gravar o índice
    sujaria a árvore e nada seria reaproveitado); schema/JSON inválido recalcula.
    `execution/impacto.py` (`impacto_de`, `vizinhanca_para_contexto`);
    `workspace.DIRETORIOS_IGNORADOS` público + `.aso/index/` no `.gitignore` do alvo.
  * Usos: discovery recebe `mapa_do_repositorio` no pedido e tem `componentes_afetados` e
    evidências conferidos contra o índice (evento `DiscoveryRun` registra `indice_commit` e
    `componentes_descartados`); revisão recebe `ImpactoEstrutural` (dependentes + testes dos
    arquivos do diff); contexto do card ganha o item `codigo` (arquivos citados =
    `linked_files` + componentes do discovery aprovado, no máximo 5 — sem citação o índice
    nem é construído).
  * Medição (critério 1): 642 arquivos, 3.163 símbolos, 216 testes, 206 entradas, ~1,0 s,
    ~388 KB de JSON no próprio repositório do ASO.
  * Testes: `tests/integration/test_indice_estrutural.py` (33). Negativos/governança:
    `test_segredos_caches_e_binarios_nunca_entram_no_indice`, `test_regra_de_elegibilidade`
    (12 casos), `test_arvore_suja_nao_grava_nem_reaproveita`, `test_indice_corrompido_e_refeito`,
    `test_discovery_descarta_componente_que_nao_existe_no_indice`,
    `test_card_sem_arquivo_citado_nao_paga_indice`. Ajustado:
    `test_perguntas_com_repositorio` usa `_mudancas_do_projeto` (ignora `.aso/`, artefato do
    runtime — a regra vigiada é o agente não escrever no código).
  * Validação: ruff check/format OK · mypy strict OK · lint-imports KEPT · alembic
    upgrade+check OK (sem migration) · pytest 1789 passed / 7 skipped / 94.82%.
    Docker/Postgres não exigido (sem persistência/boot).
  * Decisões: sem `tree-sitter`/`ctags` (dependência nativa no container/CI por precisão em
    linguagens que o ASO não indexa a fundo hoje) e sem embeddings/banco vetorial — o índice
    existe para VERIFICAR resposta, o que exige fato exato; a ADR-0077 registra o porquê e a
    imprecisão declarada de TS/JS.

* MEL-52 — consultas sem hidratar agregados (sem ADR: aplica o padrão da ADR-0038/ADR-0051).
  * Implementado: portas `orchestration_of_approval`, `approvals(status, orchestration_ids)`,
    `count_events_by_type` e `amostras_de_aprendizado` (SQL + memória, mesmo contrato) e
    `AgentRunRepository.agregados_de_execucao` (COUNT/AVG/SUM(case) em `agent_runs`);
    `_find_approval` hidrata só a dona; `list_all_approvals` projeta das linhas com filtros na
    consulta (rota `/v1/approvals`, `header_summary`, `dashboard_summary`);
    `MetricsService.execution_metrics` usa `agent_runs` + `COUNT GROUP BY type` e ganhou o campo
    `origem` (`agent_runs|eventos`, com queda para o log quando não há run);
    `aprendizado.AmostraDeAprendizado` + `snapshots_da_amostra`/`indicadores_da_amostra` deixam a
    aritmética única para o relatório de uma demanda e para o global.
  * Testes: `tests/integration/test_leituras_sem_hidratar.py` (10) — repositório espião conta
    `load()` (decidir: `[dona]`; inexistente/listagem/aprendizado global: `[]`) e comparativos
    reproduzem o cálculo antigo (aprovações, métricas contra a timeline, relatório inteiro por
    `dataclasses.asdict`, paridade entre os dois adapters). Ajustados 3 testes que mutavam o
    bundle sem gravar.
  * Validação: ruff check/format OK · mypy strict OK · lint-imports KEPT · alembic upgrade+check
    OK (sem migration) · pytest 1799 passed / 7 skipped / 94.81% · Docker/Postgres: /health 200,
    smoke OK, `/v1/approvals?status=pending`, approve, `execution-metrics`
    (`origem=agent_runs`, média vinda do `numeric`) e `/v1/learning` conferidos no container.
  * Decisão: `execution_timeline` (custo por card) continua lendo o log — é a única fonte com
    `uso_origem` por evento já materializada e não estava nos critérios; migrar para `agent_runs`
    é candidato a task própria se virar gargalo.

## Task em andamento

* ID: MEL-55 — consolidar a UI legada e as páginas novas (ADR-0078, supersede a decisão da
  ADR-0036 de manter as páginas legadas intocadas)
* Inventário (feito, por rota de API exclusiva de cada página legada):
  * `index.html` (console técnico) — 33 exclusivas: catálogo de executores (CRUD + sync),
    snapshots (lista, diff, restore-section + preview), patches, conflitos (+resolve), SLO
    (`slo`, `slo-history`, `slo/evaluate`), worktrees (+prune), `execution-timeline`, `audit` por
    demanda, `autopilot`, `run-phase`, `quality-gates/run`, `cards/{}/run|race|move|open-pr|qa`,
    `pulls/{}/ci|merge|review`, `docs-drift`/`docs-heal`, `fs/dirs`, `fs/analyze/stream`.
  * `detalhe.html` (sala de controle) — 12 exclusivas: `next-step`, `agents/{etapa}`
    (atribuição por etapa), `autopilot`, `quality-gates/run`, `spec/run|review|approve`,
    `validation-checks/suggest`, `deploy` + `deploy/config`, `docs-heal`, `/v1/phases`.
  * `macro.html` — 3: `fs/dirs`, `projects/{}/events`, `projects/{}/restore`.
  * `nova.html` — 1: `fs/analyze/stream`.
* Plano em 4 etapas (cada uma com bateria): (1) módulo JS compartilhado (`aso-api.js`: fetch com
  token, erros 403/409, polling de job 202) + as 4 seções placeholder com conteúdo real
  (`modelos` = catálogo de executores, `configuracoes` = hub de ajustes + projetos,
  `incidentes` = lista cross-demanda, `esteira` = sala de controle por demanda);
  (2) migrar para `demanda-detalhe` o que só existia no console (snapshots/diff/restore, patches,
  conflitos, SLO, worktrees, execution-timeline); (3) migrar a sala de controle de `detalhe.html`
  para `/ui/esteira?id=` (next-step, atribuição por etapa, autopilot, gate, spec) e o picker de
  pasta/análise para `demanda-nova`; (4) rotas legadas redirecionam, arquivos removidos, testes de
  HTML e smoke atualizados, ADR-0078.
* Etapa 1 OK: `static/aso-api.js` (token/api/esc/mensagens 403-409 + polling de job; `jobs.js`
  virou shim que delega), `/ui/modelos` = catálogo de executores real (campos da ADR-0076),
  `/ui/incidentes` = lista cross-demanda com nova rota `GET /v1/incidents` (consulta no
  repositório, SQL + memória), `/ui/configuracoes` = hub (atalhos + projetos com criar/arquivar/
  restaurar/histórico, migrados de `macro.html` + estado do runtime).
* Etapa 2 OK: `demanda-detalhe` ganhou a aba **Governança** (patches, conflitos + resolver,
  snapshots + diff + restaurar seção com dry-run, orçamento de erro + avaliar + histórico,
  worktrees + prune) e a aba Execuções passou a mostrar tempo/custo por card
  (`execution-timeline`); a página migrou para o módulo compartilhado.
* Testes: `tests/integration/test_consolidacao_ui.py` (14).
* Etapa 3 OK: `/ui/esteira?id=` é a sala de controle (conteúdo de `detalhe.html` dentro do shell,
  com seletor de demanda sem `?id=`); pré-análise da pasta migrada para `demanda-nova`; navegador
  de pastas migrado para `configuracoes`.
* Etapa 4 OK: `/ui/`, `/ui/nova`, `/ui/detalhe` e `/ui/console` respondem 307 preservando a query;
  os 4 arquivos legados removidos; todas as 21 páginas usam `aso-api.js` e montam a sidebar;
  links internos repontados; smoke atualizado (segue redirecionamento + checa as 4 seções);
  ADR-0078; docs (mapa-paginas reescrito, README, design-system, plano-fidelidade, index).
* Estado: validando (bateria completa em execução)

## Bloqueios

* MEL-04 — **aguardando decisão do operador**. Causa: a própria task diz "muda o fluxo que o
  CLAUDE.md impõe aos agentes deste repositório — decisão do operador; confirmar antes de
  mover" (mover `.aso/context|kanban|snapshots|quality-gates|reviews`, `specs/`, `docs/phases`
  para `docs/historico/`). Ação necessária: operador confirmar a mudança de caminhos. Não
  bloqueia MEL-03/MEL-05/MEL-3x.

* DISCOVERED-05 — `docs/api.md` ainda lista 29 endpoints que não existem no contrato gerado
  (ex.: `/v1/agents/{id}/run`, `/v1/agent-runs/{id}/cancel`, `/v1/cards/{id}/run`,
  `/v1/boards`, `/v1/providers`, `/v1/cli-agents`, `/v1/snapshots/{id}/restore`).
  * Impacto: leitor procura cancelamento/execução em rotas inexistentes; contradiz ADR-0064.
  * Evidência: comparação de `docs/api.md` × `contracts/openapi.json` em 2026-09-15 (108 paths
    citados, 29 sem correspondência). MEL-02 corrigiu outras contradições, não esta seção.
  * Sugestão: teste que extrai os paths de `docs/api.md` e exige que existam no contrato gerado
    (extensão da MEL-03), removendo as seções fantasmas — cabe na MEL-07 ou numa task curta.

## Próximas tasks elegíveis

1. MEL-55 (consolidar UI) · MEL-06 (refs de docs)
2. MEL-04 (aguarda decisão do operador) → MEL-07

## Classificação do backlog (verificada em 2026-09-15 contra código @164c6ab)

* DONE: MEL-01, MEL-02, MEL-03, MEL-05, MEL-10…MEL-20, MEL-30, MEL-31, MEL-32, MEL-33, MEL-34,
  MEL-40, MEL-41, MEL-36, MEL-35, MEL-42, MEL-43, MEL-51, MEL-50, MEL-53, MEL-54, MEL-44, MEL-52
* IN_PROGRESS: —
* READY: MEL-03, MEL-04, MEL-06, MEL-40, MEL-44, MEL-42, MEL-43, MEL-54,
  MEL-30, MEL-35, MEL-36, MEL-51, MEL-55
* WAITING_DEPENDENCY: demais (ver coluna "Depende de" no README)
* Nenhuma MEL no board.json nem no CHANGELOG antes desta sessão.

## Descobertas fora de escopo (DISCOVERED-NN)

* DISCOVERED-04 — `_advance_after_phase_gate` usa `approval.payload["phase"]` só para achar a
  próxima fase, mas `advance_phase` avança a `current_phase`. Uma aprovação `fase_gate` antiga
  (de uma fase já passada) aprovada depois avançaria a fase corrente. Mitigado pela MEL-10
  (exige gate liberado da fase corrente), mas a aprovação continua sem conferir a fase.
  Sugestão: recusar/cancelar aprovação `fase_gate` cuja `phase` ≠ `current_phase` (MEL-20 ou
  MEL-32). Não corrigido.

* DISCOVERED-03 — **PARCIAL (MEL-30 mascara `agent_runs`)** — saída de agente (stdout/stderr em eventos, `block_reason`, logs de execução)
  não é mascarada: um agente que imprimir o valor de um segredo (ex.: variável de ambiente)
  o persiste no banco/timeline. Impacto: regra 9. Evidência: nenhuma função de redação em
  `src/aso` (`grep -rn "redact\|mascar" src/aso` vazio). Sugestão: task nova de redação de
  segredos conhecidos (valores de `api_key_env`, `ASO_API_KEYS`) antes de persistir saída —
  candidata a incorporar em MEL-30 (agent_runs). Não corrigido.

* DISCOVERED-02 — `Dockerfile` não copia `scripts/` para a imagem, mas o README orienta usar
  `/app/scripts/aso-agent-wrapper.sh` no comando CLI do executor. Impacto: perfil CLI via
  wrapper não funciona dentro do container sem volume. Evidência: `grep COPY Dockerfile`
  (só pyproject, src, migrations, alembic.ini, entrypoint). Sugestão: copiar `scripts/` na
  imagem (MEL-54 catálogo de executores ou MEL-02 docs). Não corrigido.

* DISCOVERED-01 — **FECHADA na MEL-20** — `run_plan` não verificava kill-switch (`status == "cancelled"`) nem
  orçamento (`_recusar_se_orcamento_estourado`), ao contrário de `run_card`/`race_card`.
  Impacto: orquestração cancelada ou com orçamento estourado ainda executa via `run-plan`.
  Evidência: `OrchestrationService.run_plan` chama `_execute_wave` direto, sem os guards.
  Sugestão: MEL-20 ou MEL-32. MEL-13 adicionou claim em `run_plan`, mas os guards
  de kill-switch/orçamento continuam ausentes ali. Não corrigido.

## Observações para o próximo agente

* Todas as MEL nasceram na mesma revisão (`164c6ab`); números de linha citados podem ter
  deslocado — localize pela função.
* O `/loop` autônomo executa uma MEL por vez com bateria DoD completa ao fim de cada uma.
* Executores: em tempo de execução só o catálogo vale (ADR-0076). Ao rodar testes que sobem
  `build_service`, `ASO_EXECUTORS_FILE` já é isolado em `tests/conftest.py` — não remova: a
  leitura do store REGRAVA o arquivo migrado e apontaria para o `.aso/executors.json` do operador.
