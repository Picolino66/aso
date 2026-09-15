"""OrchestrationService — façade do Control Plane usada por API e CLI (ADR-0066).

Toda a lógica mora nos serviços de `aso.application` (um por caso de uso), montados em
`application/composicao.py`. Aqui ficam só: a resolução dos colaboradores (repositórios,
funções de agente e limites) e a tabela de `Delegado`, que expõe cada método com a
assinatura do serviço de origem — a API pública não mudou na extração (MEL-32).
"""

from __future__ import annotations

from aso.agents.executor import ExecutionProvider
from aso.application.agent_catalog_service import AgentCatalogService
from aso.application.agent_task import AgentTaskService
from aso.application.approvals import ApprovalService
from aso.application.bundles import BundleStore
from aso.application.candidates import CandidateRaceService
from aso.application.cards import CardService
from aso.application.catalogs import CatalogService
from aso.application.classificacao import ClassificationService
from aso.application.composicao import Colaboradores, LimitesDoRuntime, compor_servicos
from aso.application.delegacao import Delegado
from aso.application.delivery import DeliveryService
from aso.application.docs_first import DocsFirstService
from aso.application.execution import ExecutionService
from aso.application.governanca import GovernanceOpsService
from aso.application.insights import InsightService
from aso.application.intake import IntakeService
from aso.application.preparation import PreparationService
from aso.application.project_service import ProjectService
from aso.application.qa import QaService
from aso.application.queries import QueryService
from aso.application.recovery import RecoveryService
from aso.application.release import ReleaseService
from aso.application.routing_rule_service import RoutingRuleService
from aso.application.settings import ExecutionSettingsService
from aso.application.workflow import WorkflowService
from aso.control.discovery import DiscoveryService
from aso.control.naming import NamingService
from aso.control.review import ReviewService
from aso.control.spec import SpecService
from aso.control.triage import TriageService
from aso.execution.catalog import ExecutorCatalog
from aso.execution.settings_store import ExecutorSettingsStore
from aso.observability.agent_log import AgentLogBus
from aso.observability.agent_runs import (
    AgentRunRepository,
    InMemoryAgentRunRepository,
)
from aso.observability.logging import get_logger
from aso.persistence.memory import (
    InMemoryAgentDefinitionRepository,
    InMemoryOrchestrationRepository,
    InMemoryProjectRepository,
    InMemoryRoutingRuleRepository,
)
from aso.persistence.ports import (
    AgentDefinitionRepository,
    OrchestrationRepository,
    ProjectRepository,
    RoutingRuleRepository,
)
from aso.shared.cache import TTLCache
from aso.shared.ids import gen_id


class OrchestrationService:
    """Façade: métodos públicos delegados aos serviços de aplicação (ADR-0066)."""

    # BundleStore
    _lock_for = Delegado("_bundle_store", BundleStore.lock_for)
    _bundle = Delegado("_bundle_store", BundleStore.get)
    _to_state = Delegado("_bundle_store", BundleStore.to_state)
    _persist = Delegado("_bundle_store", BundleStore.persist)
    _hydrate = Delegado("_bundle_store", BundleStore.hydrate)

    # QueryService
    list_all = Delegado("_queries", QueryService.list_all)
    list_orchestrations_page = Delegado("_queries", QueryService.list_orchestrations_page)
    aggregate_metrics = Delegado("_queries", QueryService.aggregate_metrics)
    header_summary = Delegado("_queries", QueryService.header_summary)
    search = Delegado("_queries", QueryService.search)
    dashboard_summary = Delegado("_queries", QueryService.dashboard_summary)
    recent_activity = Delegado("_queries", QueryService.recent_activity)
    audit_page = Delegado("_queries", QueryService.audit_page)
    export_audit = Delegado("_queries", QueryService.export_audit)
    get_context = Delegado("_queries", QueryService.get_context)
    get_plan = Delegado("_queries", QueryService.get_plan)
    get_cards = Delegado("_queries", QueryService.get_cards)
    get_card_tree = Delegado("_queries", QueryService.get_card_tree)
    get_card = Delegado("_queries", QueryService.get_card)
    get_card_events = Delegado("_queries", QueryService.get_card_events)
    list_adrs = Delegado("_queries", QueryService.list_adrs)
    list_snapshots = Delegado("_queries", QueryService.list_snapshots)
    timeline = Delegado("_queries", QueryService.timeline)
    conflicts = Delegado("_queries", QueryService.conflicts)
    list_all_approvals = Delegado("_queries", QueryService.list_all_approvals)
    count_cards_by_status = Delegado("_queries", QueryService.count_cards_by_status)
    search_adrs = Delegado("_queries", QueryService.search_adrs)
    timeline_page = Delegado("_queries", QueryService.timeline_page)
    list_pulls = Delegado("_queries", QueryService.list_pulls)
    list_review_comments = Delegado("_queries", QueryService.list_review_comments)
    list_patches = Delegado("_queries", QueryService.list_patches)
    list_gate_results = Delegado("_queries", QueryService.list_gate_results)
    list_approvals = Delegado("_queries", QueryService.list_approvals)
    list_candidate_runs = Delegado("_queries", QueryService.list_candidate_runs)
    list_slo_evaluations = Delegado("_queries", QueryService.list_slo_evaluations)
    list_incidents = Delegado("_queries", QueryService.list_incidents)
    list_bug_reports = Delegado("_queries", QueryService.list_bug_reports)
    get = Delegado("_queries", QueryService.get)

    # ExecutionSettingsService
    resolve_provider = Delegado("_settings", ExecutionSettingsService.resolve_provider)
    _effective_executor = Delegado("_settings", ExecutionSettingsService._effective_executor)
    _effective_effort = Delegado("_settings", ExecutionSettingsService._effective_effort)
    _provider_for = Delegado("_settings", ExecutionSettingsService._provider_for)
    _workspace_for = Delegado("_settings", ExecutionSettingsService._workspace_for)
    _executor_availability = Delegado("_settings", ExecutionSettingsService._executor_availability)
    update_execution_settings = Delegado(
        "_settings", ExecutionSettingsService.update_execution_settings
    )
    get_validation_checks = Delegado("_settings", ExecutionSettingsService.get_validation_checks)
    set_validation_checks = Delegado("_settings", ExecutionSettingsService.set_validation_checks)
    suggest_validation_checks = Delegado(
        "_settings", ExecutionSettingsService.suggest_validation_checks
    )
    set_orcamento = Delegado("_settings", ExecutionSettingsService.set_orcamento)
    set_agent_assignment = Delegado("_settings", ExecutionSettingsService.set_agent_assignment)
    clear_agent_assignment = Delegado("_settings", ExecutionSettingsService.clear_agent_assignment)
    increase_card_effort = Delegado("_settings", ExecutionSettingsService.increase_card_effort)
    transfer_card_model = Delegado("_settings", ExecutionSettingsService.transfer_card_model)
    list_worktrees = Delegado("_settings", ExecutionSettingsService.list_worktrees)
    prune_worktrees = Delegado("_settings", ExecutionSettingsService.prune_worktrees)

    # AgentTaskService
    _build_task = Delegado("_agent_task", AgentTaskService._build_task)
    _salvar_run = Delegado("_agent_task", AgentTaskService._salvar_run)
    _perguntar_registrando = Delegado("_agent_task", AgentTaskService._perguntar_registrando)
    _abrir_run = Delegado("_agent_task", AgentTaskService._abrir_run)
    _fechar_run = Delegado("_agent_task", AgentTaskService._fechar_run)
    _registrar_decisao_no_run = Delegado("_agent_task", AgentTaskService._registrar_decisao_no_run)
    list_agent_runs = Delegado("_agent_task", AgentTaskService.list_agent_runs)
    get_agent_run = Delegado("_agent_task", AgentTaskService.get_agent_run)

    # DeliveryService
    open_pr = Delegado("_delivery", DeliveryService.open_pr)
    _find_pr = Delegado("_delivery", DeliveryService._find_pr)
    report_ci = Delegado("_delivery", DeliveryService.report_ci)
    report_review = Delegado("_delivery", DeliveryService.report_review)
    _resolve_reviewer = Delegado("_delivery", DeliveryService._resolve_reviewer)
    get_review = Delegado("_delivery", DeliveryService.get_review)
    run_review = Delegado("_delivery", DeliveryService.run_review)
    _apply_review_verdict = Delegado("_delivery", DeliveryService._apply_review_verdict)
    merge_pr = Delegado("_delivery", DeliveryService.merge_pr)
    run_pr_ci = Delegado("_delivery", DeliveryService.run_pr_ci)
    resolve_review_comment = Delegado("_delivery", DeliveryService.resolve_review_comment)

    # DocsFirstService
    analyze_folder = Delegado("_docs_first", DocsFirstService.analyze_folder)
    docs_drift = Delegado("_docs_first", DocsFirstService.docs_drift)
    heal_docs = Delegado("_docs_first", DocsFirstService.heal_docs)

    # CardService
    create_card = Delegado("_cards", CardService.create_card)
    move_card = Delegado("_cards", CardService.move_card)
    move_card_validado = Delegado("_cards", CardService.move_card_validado)
    kanban_board = Delegado("_cards", CardService.kanban_board)
    block_card = Delegado("_cards", CardService.block_card)
    unblock_card = Delegado("_cards", CardService.unblock_card)
    cancel_card = Delegado("_cards", CardService.cancel_card)
    assign_agent = Delegado("_cards", CardService.assign_agent)
    cards_by_status = Delegado("_cards", CardService.cards_by_status)
    adrs_by_status = Delegado("_cards", CardService.adrs_by_status)
    cards_linked_to_adr = Delegado("_cards", CardService.cards_linked_to_adr)
    filter_cards = Delegado("_cards", CardService.filter_cards)
    get_card_failures = Delegado("_cards", CardService.get_card_failures)
    get_card_closure = Delegado("_cards", CardService.get_card_closure)
    get_card_failure_diagnostics = Delegado("_cards", CardService.get_card_failure_diagnostics)
    get_card_changed_files = Delegado("_cards", CardService.get_card_changed_files)
    get_card_diff_stats = Delegado("_cards", CardService.get_card_diff_stats)
    pause_card = Delegado("_cards", CardService.pause_card)
    add_card_context = Delegado("_cards", CardService.add_card_context)
    recover_invalid_execution = Delegado("_cards", CardService.recover_invalid_execution)

    # ExecutionService
    _recuperar_execucoes_interrompidas = Delegado(
        "_execution", ExecutionService._recuperar_execucoes_interrompidas
    )
    _reivindicar_card = Delegado("_execution", ExecutionService._reivindicar_card)
    _execute_isolated = Delegado("_execution", ExecutionService._execute_isolated)
    _execute_wave = Delegado("_execution", ExecutionService._execute_wave)
    _route_failure = Delegado("_execution", ExecutionService._route_failure)
    _apply_execution = Delegado("_execution", ExecutionService._apply_execution)
    run_card = Delegado("_execution", ExecutionService.run_card)
    _recusar_se_orcamento_estourado = Delegado(
        "_execution", ExecutionService._recusar_se_orcamento_estourado
    )
    _gasto_usd = Delegado("_execution", ExecutionService._gasto_usd)

    # CandidateRaceService
    race_card = Delegado("_candidates", CandidateRaceService.race_card)

    # PreparationService
    run_discovery = Delegado("_preparation", PreparationService.run_discovery)
    get_discovery_report = Delegado("_preparation", PreparationService.get_discovery_report)
    get_discovery_history = Delegado("_preparation", PreparationService.get_discovery_history)
    get_discovery_approval_criteria = Delegado(
        "_preparation", PreparationService.get_discovery_approval_criteria
    )
    decide_discovery = Delegado("_preparation", PreparationService.decide_discovery)
    run_spec = Delegado("_preparation", PreparationService.run_spec)
    get_spec = Delegado("_preparation", PreparationService.get_spec)
    get_spec_history = Delegado("_preparation", PreparationService.get_spec_history)
    run_spec_review = Delegado("_preparation", PreparationService.run_spec_review)
    approve_spec = Delegado("_preparation", PreparationService.approve_spec)
    list_documentos = Delegado("_preparation", PreparationService.list_documentos)
    get_documento = Delegado("_preparation", PreparationService.get_documento)
    get_documento_history = Delegado("_preparation", PreparationService.get_documento_history)
    diff_documento = Delegado("_preparation", PreparationService.diff_documento)
    save_documento = Delegado("_preparation", PreparationService.save_documento)
    review_documento = Delegado("_preparation", PreparationService.review_documento)
    list_documento_comments = Delegado("_preparation", PreparationService.list_documento_comments)
    create_documento_comment = Delegado("_preparation", PreparationService.create_documento_comment)
    resolve_documento_comment = Delegado(
        "_preparation", PreparationService.resolve_documento_comment
    )

    # QaService
    register_qa_check = Delegado("_qa", QaService.register_qa_check)
    get_qa_checks = Delegado("_qa", QaService.get_qa_checks)
    fail_qa_check = Delegado("_qa", QaService.fail_qa_check)
    create_bug_report = Delegado("_qa", QaService.create_bug_report)
    get_bug_report = Delegado("_qa", QaService.get_bug_report)
    get_demand_closure = Delegado("_qa", QaService.get_demand_closure)
    export_demand_closure = Delegado("_qa", QaService.export_demand_closure)

    # ReleaseService
    set_deploy_config = Delegado("_release", ReleaseService.set_deploy_config)
    set_deploy_pipeline = Delegado("_release", ReleaseService.set_deploy_pipeline)
    get_deploy_pipeline = Delegado("_release", ReleaseService.get_deploy_pipeline)
    run_deploy = Delegado("_release", ReleaseService.run_deploy)
    get_deploy = Delegado("_release", ReleaseService.get_deploy)
    get_deploy_history = Delegado("_release", ReleaseService.get_deploy_history)
    validate_deploy = Delegado("_release", ReleaseService.validate_deploy)
    decide_deploy = Delegado("_release", ReleaseService.decide_deploy)
    rollback_deploy = Delegado("_release", ReleaseService.rollback_deploy)
    get_deploy_approval_checklist = Delegado(
        "_release", ReleaseService.get_deploy_approval_checklist
    )
    get_deploy_health = Delegado("_release", ReleaseService.get_deploy_health)
    get_rollback_checklist = Delegado("_release", ReleaseService.get_rollback_checklist)
    get_incident = Delegado("_release", ReleaseService.get_incident)
    investigate_incident = Delegado("_release", ReleaseService.investigate_incident)
    resolve_incident = Delegado("_release", ReleaseService.resolve_incident)

    # WorkflowService
    _advance_after_phase_gate = Delegado("_workflow", WorkflowService._advance_after_phase_gate)
    definir_agendador_de_fase = Delegado("_workflow", WorkflowService.definir_agendador_de_fase)
    start_autopilot = Delegado("_workflow", WorkflowService.start_autopilot)
    run_plan = Delegado("_workflow", WorkflowService.run_plan)
    run_quality_gate = Delegado("_workflow", WorkflowService.run_quality_gate)
    _maybe_autoheal_docs = Delegado("_workflow", WorkflowService._maybe_autoheal_docs)
    run_phase = Delegado("_workflow", WorkflowService.run_phase)
    advance_phase = Delegado("_workflow", WorkflowService.advance_phase)

    # RecoveryService
    retry = Delegado("_recovery", RecoveryService.retry)
    route_card = Delegado("_recovery", RecoveryService.route_card)

    # ApprovalService
    request_approval = Delegado("_approvals", ApprovalService.request_approval)
    get_approval = Delegado("_approvals", ApprovalService.get_approval)
    decide_approval = Delegado("_approvals", ApprovalService.decide_approval)
    _find_approval = Delegado("_approvals", ApprovalService._find_approval)
    rollback = Delegado("_approvals", ApprovalService.rollback)
    restaurar_ledger = Delegado("_approvals", ApprovalService.restaurar_ledger)
    cancel = Delegado("_approvals", ApprovalService.cancel)
    resume = Delegado("_approvals", ApprovalService.resume)
    preview_restore_section = Delegado("_approvals", ApprovalService.preview_restore_section)
    restore_section = Delegado("_approvals", ApprovalService.restore_section)
    request_card_help = Delegado("_approvals", ApprovalService.request_card_help)

    # IntakeService
    planejar = Delegado("_intake", IntakeService.planejar)
    planejar_na_criacao = Delegado("_intake", IntakeService.planejar_na_criacao)
    create_orchestration = Delegado("_intake", IntakeService.create_orchestration)
    _apply_routing_rule = Delegado("_intake", IntakeService._apply_routing_rule)
    registrar_falha_de_planejamento = Delegado(
        "_intake", IntakeService.registrar_falha_de_planejamento
    )
    populate_from_plan = Delegado("_intake", IntakeService.populate_from_plan)
    _triage_executor = Delegado("_intake", IntakeService._triage_executor)
    triage_demand = Delegado("_intake", IntakeService.triage_demand)
    create_with_triage = Delegado("_intake", IntakeService.create_with_triage)
    get_demand_brief = Delegado("_intake", IntakeService.get_demand_brief)
    set_demand_brief = Delegado("_intake", IntakeService.set_demand_brief)
    retriage_demand = Delegado("_intake", IntakeService.retriage_demand)

    # CatalogService
    create_project = Delegado("_catalogs", CatalogService.create_project)
    list_projects = Delegado("_catalogs", CatalogService.list_projects)
    get_project = Delegado("_catalogs", CatalogService.get_project)
    update_project = Delegado("_catalogs", CatalogService.update_project)
    archive_project = Delegado("_catalogs", CatalogService.archive_project)
    restore_project = Delegado("_catalogs", CatalogService.restore_project)
    project_events = Delegado("_catalogs", CatalogService.project_events)
    list_executors = Delegado("_catalogs", CatalogService.list_executors)
    sync_codex_executors = Delegado("_catalogs", CatalogService.sync_codex_executors)
    save_executor = Delegado("_catalogs", CatalogService.save_executor)
    delete_executor = Delegado("_catalogs", CatalogService.delete_executor)
    list_routing_rules = Delegado("_catalogs", CatalogService.list_routing_rules)
    create_routing_rule = Delegado("_catalogs", CatalogService.create_routing_rule)
    update_routing_rule = Delegado("_catalogs", CatalogService.update_routing_rule)
    delete_routing_rule = Delegado("_catalogs", CatalogService.delete_routing_rule)
    reorder_routing_rules = Delegado("_catalogs", CatalogService.reorder_routing_rules)
    preview_routing_rule = Delegado("_catalogs", CatalogService.preview_routing_rule)
    list_agent_definitions = Delegado("_catalogs", CatalogService.list_agent_definitions)
    get_agent_definition = Delegado("_catalogs", CatalogService.get_agent_definition)
    create_agent_definition = Delegado("_catalogs", CatalogService.create_agent_definition)
    update_agent_definition = Delegado("_catalogs", CatalogService.update_agent_definition)
    delete_agent_definition = Delegado("_catalogs", CatalogService.delete_agent_definition)
    _validate_executor = Delegado("_catalogs", CatalogService._validate_executor)

    # ClassificationService
    duplicate_orchestration = Delegado(
        "_classificacao", ClassificationService.duplicate_orchestration
    )
    update_classification = Delegado("_classificacao", ClassificationService.update_classification)
    _replan_if_untouched = Delegado("_classificacao", ClassificationService._replan_if_untouched)

    # InsightService
    get_learning_report = Delegado("_insights", InsightService.get_learning_report)
    get_learning_report_global = Delegado("_insights", InsightService.get_learning_report_global)
    _estimar_custo_e_tempo = Delegado("_insights", InsightService._estimar_custo_e_tempo)
    preview_recommendation = Delegado("_insights", InsightService.preview_recommendation)
    get_agent_real_roles = Delegado("_insights", InsightService.get_agent_real_roles)
    next_step = Delegado("_insights", InsightService.next_step)
    get_preparation_checklist = Delegado("_insights", InsightService.get_preparation_checklist)

    # GovernanceOpsService
    _propose_resolution = Delegado("_governanca", GovernanceOpsService._propose_resolution)
    resolve_conflict = Delegado("_governanca", GovernanceOpsService.resolve_conflict)
    get_patch = Delegado("_governanca", GovernanceOpsService.get_patch)
    submit_patch = Delegado("_governanca", GovernanceOpsService.submit_patch)
    _submit_with_approval = Delegado("_governanca", GovernanceOpsService._submit_with_approval)
    snapshot_diff = Delegado("_governanca", GovernanceOpsService.snapshot_diff)
    find_gate_result = Delegado("_governanca", GovernanceOpsService.find_gate_result)
    audit = Delegado("_governanca", GovernanceOpsService.audit)
    record_slo_evaluation = Delegado("_governanca", GovernanceOpsService.record_slo_evaluation)
    add_feedback = Delegado("_governanca", GovernanceOpsService.add_feedback)
    agent_log = Delegado("_governanca", GovernanceOpsService.agent_log)

    # Auxiliares estáticos reexpostos (usados por testes e callbacks)
    _fontes_do_contexto = staticmethod(AgentTaskService._fontes_do_contexto)
    _liberar_claim = staticmethod(ExecutionService._liberar_claim)
    _recusar_se_em_execucao = staticmethod(ExecutionService._recusar_se_em_execucao)
    _pending_dependencies = staticmethod(ExecutionService._pending_dependencies)
    _criar_tarefa_vinculada = staticmethod(ExecutionService._criar_tarefa_vinculada)
    _recusar_se_estrategia_pendente = staticmethod(ExecutionService._recusar_se_estrategia_pendente)
    _next_phase = staticmethod(WorkflowService._next_phase)
    _max_tentativas_da_regra = staticmethod(IntakeService._max_tentativas_da_regra)
    _assignment = staticmethod(ExecutionSettingsService._assignment)

    def __init__(
        self,
        provider: ExecutionProvider | None = None,
        repository: OrchestrationRepository | None = None,
        project_repository: ProjectRepository | None = None,
        routing_rule_repository: RoutingRuleRepository | None = None,
        agent_definition_repository: AgentDefinitionRepository | None = None,
        *,
        agent_run_repository: AgentRunRepository | None = None,
        max_races_per_card: int | None = None,
        max_slo_samples: int | None = None,
        max_escalonamentos: int | None = None,
        effort_automatico: bool | None = None,
        catalog: ExecutorCatalog | None = None,
        executor_store: ExecutorSettingsStore | None = None,
        naming: NamingService | None = None,
        triage: TriageService | None = None,
        review: ReviewService | None = None,
        discovery: DiscoveryService | None = None,
        spec: SpecService | None = None,
        max_rodadas_doc: int | None = None,
        log_bus: AgentLogBus | None = None,
    ) -> None:
        # Registro de execuções de agente (ADR-0065): fora do agregado, append-only.
        self._agent_runs: AgentRunRepository = agent_run_repository or InMemoryAgentRunRepository()
        # Identidade desta instância do runtime (ADR-0058): dono dos claims de execução.
        # Um claim com outro dono visto na reidratação veio de um processo que morreu.
        self._instancia_id = gen_id("runtime")
        self._provider = provider
        # Catálogo de executores selecionáveis por etapa (Claude/Codex/DeepSeek/…).
        self._catalog = catalog
        # Batiza branches/commits a partir do card (ADR-0014); sem agente nomeador
        # configurado, resolve tudo de forma determinística e sem custo.
        self._naming = naming or NamingService(catalog)
        # Interpreta a demanda em ficha estruturada (§1/§2 do fluxo.md); sem agente de
        # triagem configurado, cai na heurística determinística (nunca falha).
        self._triage = triage or TriageService(catalog)
        # Revisão independente de código a partir do diff (§14, ADR-0017); sem agente
        # revisor configurado (ou com falha), o fallback é SEMPRE `necessita_humano` —
        # nunca `aprovado` (diferente de naming/triage, não existe revisão determinística).
        self._review = review or ReviewService(catalog)
        # Relatório de discovery (§3/§4 do fluxo.md, ADR-0020); sem agente configurado
        # (ou com falha), cai na heurística determinística a partir do workspace e da
        # ficha já triada — nunca falha (mesma garantia de naming/triage).
        self._discovery = discovery or DiscoveryService(catalog)
        # Especificação da solução (§5, ADR-0021); exige discovery aprovado — sem ele,
        # `run_spec` recusa (§5: "Com o discovery aprovado").
        self._spec = spec or SpecService(catalog)
        # Saída ao vivo dos agentes CLI (ADR-0015): ring em memória, lido por polling.
        self._log_bus = log_bus or AgentLogBus()
        self._executor_store = executor_store  # persiste perfis (sem secrets)
        self._repo: OrchestrationRepository = repository or InMemoryOrchestrationRepository()
        self._projects = ProjectService(project_repository or InMemoryProjectRepository())
        # Regras de roteamento (§33, ADR-0028): declaradas pelo operador, avaliadas
        # antes da heurística do MultiAgentDecisionEngine — fallback, nunca substituição.
        self._routing_rules = RoutingRuleService(
            routing_rule_repository or InMemoryRoutingRuleRepository()
        )
        # Catálogo de agentes (Tela 30, wf §32, ADR-0053) — fonte de verdade das
        # permissões reais: `AgentRegistry.seed_from_catalog` aplica isto por
        # cima dos 16 papéis-base a cada bundle novo/reidratado.
        self._agent_catalog = AgentCatalogService(
            agent_definition_repository or InMemoryAgentDefinitionRepository()
        )
        # wf §32.2: 14 agentes-exemplo pré-provisionados — só semeia se o
        # catálogo ainda estiver vazio (idempotente, nunca sobrescreve edição).
        self._agent_catalog.seed_examples_if_empty()
        self._read_cache = TTLCache(ttl_seconds=1.0)  # cache de leitura para agregações
        self._log = get_logger()  # eventos de domínio visíveis no stdout
        self._limites = LimitesDoRuntime.resolver(
            max_rodadas_doc=max_rodadas_doc,
            max_races_per_card=max_races_per_card,
            max_slo_samples=max_slo_samples,
            max_escalonamentos=max_escalonamentos,
            effort_automatico=effort_automatico,
        )
        # Serviços de aplicação (ADR-0066): montados na raiz de composição; a tabela de
        # `Delegado` acima expõe cada um pelo atributo `_<nome>` (ex.: `_delivery`).
        servicos = compor_servicos(
            Colaboradores(
                repo=self._repo,
                agent_runs=self._agent_runs,
                projects=self._projects,
                routing_rules=self._routing_rules,
                agent_catalog=self._agent_catalog,
                read_cache=self._read_cache,
                log=self._log,
                log_bus=self._log_bus,
                executor_store=self._executor_store,
                naming=self._naming,
                triage=self._triage,
                review=self._review,
                discovery=self._discovery,
                spec=self._spec,
                instancia_id=self._instancia_id,
                limites=self._limites,
                catalogo=lambda: self._catalog,
                definir_catalogo=lambda valor: setattr(self, "_catalog", valor),
                provider=lambda: self._provider,
            )
        )
        for nome, servico in vars(servicos).items():
            setattr(self, f"_{nome}", servico)
        self._bundles = servicos.bundle_store.cache  # o MESMO dict do BundleStore
