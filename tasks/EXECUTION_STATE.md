# ASO MEL Execution State

Checkpoint oficial da execução do backlog `MEL-*` (origem: [feedback.md](../feedback.md)).
Leia depois de [tasks/README.md](README.md). Código e Git prevalecem sobre este arquivo.

## Estado geral

* Última atualização: 2026-09-15
* Branch/base: `main`
* Commit base: `164c6ab` (nenhum commit feito por agente — regra 7)
* Task atual: MEL-33 (análise)
* Última task concluída: MEL-31
* Próxima task candidata: MEL-33
* Estado: analyzing

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


## Task em andamento

* nenhuma (MEL-31 concluída; próxima: MEL-33)

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

1. MEL-33 (P1, fase 3)
2. MEL-40 · MEL-41 (P1, fase 4)
3. MEL-06 · MEL-35 · MEL-36 · MEL-42 · MEL-43 · MEL-51 · MEL-53 · MEL-54 · MEL-55 (P2)
4. MEL-04 (aguarda decisão do operador) → MEL-07

## Classificação do backlog (verificada em 2026-09-15 contra código @164c6ab)

* DONE: MEL-01, MEL-02, MEL-03, MEL-05, MEL-10…MEL-20, MEL-30, MEL-31, MEL-32, MEL-34
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
