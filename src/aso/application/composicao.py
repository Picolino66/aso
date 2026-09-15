"""Raiz de composição da camada de aplicação (MEL-32, ADR-0066).

Monta os serviços de aplicação e liga uns aos outros por construtor, na ordem das
dependências. A façade `OrchestrationService` só resolve os colaboradores (repositórios,
funções de agente, limites) e expõe os serviços; nenhum serviço conhece a façade.

`catalogo`/`provider` são funções, não valores: o catálogo de executores e o provider padrão
continuam atributos mutáveis da façade (o CatalogService troca o catálogo; testes injetam
provider), e cada serviço lê o valor atual a cada uso.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aso.agents.executor import ExecutionProvider
from aso.application.agent_catalog_service import AgentCatalogService
from aso.application.agent_task import AgentTaskService
from aso.application.approvals import ApprovalService
from aso.application.bundles import BundleStore
from aso.application.candidates import CandidateRaceService
from aso.application.cards import CardService
from aso.application.catalogs import CatalogService
from aso.application.classificacao import ClassificationService
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
from aso.observability.agent_runs import AgentRunRepository
from aso.persistence.ports import OrchestrationRepository
from aso.shared.cache import TTLCache


def _inteiro(explicito: int | None, variavel: str, padrao: str) -> int:
    return explicito if explicito is not None else int(os.environ.get(variavel, padrao))


@dataclass(frozen=True)
class LimitesDoRuntime:
    """Limites e interruptores do runtime: argumento explícito vence a variável de ambiente."""

    # Rodadas do ciclo de revisão documental (§6, ADR-0021): esgotado, a decisão escala para
    # humano — sem isto, autor e revisor podem girar indefinidamente queimando tokens.
    max_rodadas_doc: int
    # Retenção de corridas por card: evita o candidate_runs crescer sem limite.
    max_races_per_card: int
    # Retenção de amostras de SLO: evita slo_evaluations crescer sem limite.
    max_slo_samples: int
    # Limite duro do roteamento de falha (§13, ADR-0019): esgotado, a ação é sempre escalar
    # para humano — nunca deixa o laço de retry de `run_card` aberto.
    max_escalonamentos: int
    # Escolha automática de esforço (§9, ADR-0022): liga por padrão — a sugestão só preenche
    # o vazio abaixo de toda escolha humana (§4.6); `ASO_EFFORT_AUTOMATICO=0` desliga.
    effort_automatico: bool
    # Orçamento com freio (§1.2/§3.2, ADR-0026): default de orquestrações NOVAS. Sem a env,
    # `None` — nenhum teto (opt-in, não uma trava imposta a toda orquestração).
    orcamento_padrao_usd: float | None

    @classmethod
    def resolver(
        cls,
        *,
        max_rodadas_doc: int | None = None,
        max_races_per_card: int | None = None,
        max_slo_samples: int | None = None,
        max_escalonamentos: int | None = None,
        effort_automatico: bool | None = None,
    ) -> LimitesDoRuntime:
        env_orcamento = os.environ.get("ASO_ORCAMENTO_PADRAO_USD")
        return cls(
            max_rodadas_doc=_inteiro(max_rodadas_doc, "ASO_MAX_RODADAS_DOC", "3"),
            max_races_per_card=_inteiro(max_races_per_card, "ASO_MAX_RACES_PER_CARD", "20"),
            max_slo_samples=_inteiro(max_slo_samples, "ASO_MAX_SLO_SAMPLES", "200"),
            max_escalonamentos=_inteiro(max_escalonamentos, "ASO_MAX_ESCALONAMENTOS", "3"),
            effort_automatico=(
                effort_automatico
                if effort_automatico is not None
                else os.environ.get("ASO_EFFORT_AUTOMATICO", "1") != "0"
            ),
            orcamento_padrao_usd=float(env_orcamento) if env_orcamento else None,
        )


@dataclass(frozen=True)
class Colaboradores:
    """Tudo o que os serviços recebem de fora da camada de aplicação."""

    repo: OrchestrationRepository
    agent_runs: AgentRunRepository
    projects: ProjectService
    routing_rules: RoutingRuleService
    agent_catalog: AgentCatalogService
    read_cache: TTLCache
    log: Any
    log_bus: AgentLogBus
    executor_store: ExecutorSettingsStore | None
    naming: NamingService
    triage: TriageService
    review: ReviewService
    discovery: DiscoveryService
    spec: SpecService
    instancia_id: str
    limites: LimitesDoRuntime
    catalogo: Callable[[], ExecutorCatalog | None]
    definir_catalogo: Callable[[ExecutorCatalog], None]
    provider: Callable[[], ExecutionProvider | None]


class Servicos:
    """Serviços de aplicação montados (um por caso de uso, ADR-0066)."""

    bundle_store: BundleStore
    queries: QueryService
    catalogs: CatalogService
    governanca: GovernanceOpsService
    settings: ExecutionSettingsService
    agent_task: AgentTaskService
    delivery: DeliveryService
    docs_first: DocsFirstService
    cards: CardService
    execution: ExecutionService
    candidates: CandidateRaceService
    preparation: PreparationService
    qa: QaService
    release: ReleaseService
    workflow: WorkflowService
    recovery: RecoveryService
    approvals: ApprovalService
    intake: IntakeService
    classificacao: ClassificationService
    insights: InsightService


def compor_servicos(c: Colaboradores) -> Servicos:
    s = Servicos()
    limites = c.limites
    assignment = ExecutionSettingsService._assignment
    # Locks por orquestração: serializam ler-bundle → mutar → persistir sob requisições
    # concorrentes (API/CLI multithread) — evita lost-update e dupla hidratação. Cache,
    # hidratação, persistência e lock vivem no BundleStore (passo 1). Lambdas apontam para
    # serviços construídos depois (ordem de dependências).
    s.bundle_store = BundleStore(
        c.repo,
        definicoes_ativas=lambda: c.agent_catalog.list_definitions(only_active=True),
        read_cache=c.read_cache,
        ao_hidratar=lambda b: s.execution._recuperar_execucoes_interrompidas(b),
    )
    store = s.bundle_store
    # Consultas de leitura (passo 2).
    s.queries = QueryService(store, c.repo, c.read_cache)
    # Catálogos globais: projetos, executores, regras e agentes (passo 9).
    s.catalogs = CatalogService(
        projects=c.projects,
        routing_rules=c.routing_rules,
        agent_catalog=c.agent_catalog,
        executor_store=c.executor_store,
        catalogo_get=c.catalogo,
        catalogo_set=c.definir_catalogo,
        list_all=s.queries.list_all,
    )
    # Patches e conflitos do ledger, auditoria, SLO, feedback e log de agente (passo 11d).
    s.governanca = GovernanceOpsService(
        store, repository=c.repo, log_bus=c.log_bus, max_slo_samples=limites.max_slo_samples
    )
    # Configuração de execução: executor/esforço efetivos, atribuições, validações,
    # orçamento e worktrees (passo 11a).
    s.settings = ExecutionSettingsService(
        store,
        log_bus=c.log_bus,
        effort_automatico=limites.effort_automatico,
        catalogo=c.catalogo,
        provider=c.provider,
        validate_executor=s.catalogs._validate_executor,
    )
    # Tarefa do agente e registro de execuções (passo 4a).
    s.agent_task = AgentTaskService(
        store, agent_runs=c.agent_runs, naming=c.naming, log=c.log, assignment=assignment
    )
    # Entrega governada: PR, CI, revisão e merge (passo 3).
    s.delivery = DeliveryService(
        store,
        review=c.review,
        log=c.log,
        catalogo=c.catalogo,
        assignment=assignment,
        workspace_for=s.settings._workspace_for,
        perguntar_registrando=s.agent_task._perguntar_registrando,
    )
    # Docs-first do workspace: análise de pasta e self-heal via card + PR (passo 11b).
    s.docs_first = DocsFirstService(store, settings=s.settings, delivery=s.delivery, log=c.log)
    # Operações manuais do board e diagnóstico de cards (passo 11c).
    s.cards = CardService(
        store,
        repository=c.repo,
        queries=s.queries,
        settings=s.settings,
        catalogo=c.catalogo,
    )
    # Execução de cards: claim, agente, falhas e freios (passo 4b).
    s.execution = ExecutionService(
        store,
        agent_task=s.agent_task,
        delivery=s.delivery,
        agent_catalog=c.agent_catalog,
        log=c.log,
        instancia_id=c.instancia_id,
        max_escalonamentos=limites.max_escalonamentos,
        catalogo=c.catalogo,
        provider=c.provider,
        effective_effort=s.settings._effective_effort,
        effective_executor=s.settings._effective_executor,
        provider_for=s.settings._provider_for,
        resolve_provider=s.settings.resolve_provider,
        submit_with_approval=s.governanca._submit_with_approval,
    )
    # Corrida de candidatos (§26A.6) sob o claim do ExecutionService.
    s.candidates = CandidateRaceService(
        store, execution=s.execution, max_races_per_card=limites.max_races_per_card
    )
    # Preparação: discovery, especificação e documentos (passo 5).
    s.preparation = PreparationService(
        store,
        discovery=c.discovery,
        spec=c.spec,
        review=c.review,
        delivery=s.delivery,
        max_rodadas_doc=limites.max_rodadas_doc,
        catalogo=c.catalogo,
        assignment=assignment,
        max_tentativas_da_regra=IntakeService._max_tentativas_da_regra,
        perguntar_registrando=s.agent_task._perguntar_registrando,
    )
    # QA humano, bugs e encerramento (passo 6a); implantação e incidentes (passo 6b).
    s.qa = QaService(store, max_escalonamentos=limites.max_escalonamentos, catalogo=c.catalogo)
    s.release = ReleaseService(store)
    # Esteira: fases, gate, autopilot e plano (passo 7) — único lugar que muda fase.
    s.workflow = WorkflowService(
        store,
        execution=s.execution,
        agent_task=s.agent_task,
        log=c.log,
        max_escalonamentos=limites.max_escalonamentos,
        catalogo=c.catalogo,
        assignment=assignment,
        effective_effort=s.settings._effective_effort,
        effective_executor=s.settings._effective_executor,
        provider_for=s.settings._provider_for,
        analyze_folder=s.docs_first.analyze_folder,
        heal_docs=s.docs_first.heal_docs,
    )
    s.recovery = RecoveryService(
        store,
        execution=s.execution,
        max_escalonamentos=limites.max_escalonamentos,
        catalogo=c.catalogo,
        effective_executor=s.settings._effective_executor,
    )
    # Aprovações, kill-switch e restauração do ledger (passo 7).
    s.approvals = ApprovalService(
        store, repository=c.repo, avancar_apos_gate=s.workflow._advance_after_phase_gate
    )
    # Entrada da demanda: criação, triagem e planejamento (passo 8).
    s.intake = IntakeService(
        store,
        triage=c.triage,
        projects=c.projects,
        routing_rules=c.routing_rules,
        agent_catalog=c.agent_catalog,
        orcamento_padrao_usd=limites.orcamento_padrao_usd,
        catalogo=c.catalogo,
        assignment=assignment,
        validate_executor=s.catalogs._validate_executor,
        replan_if_untouched=lambda *a, **kw: s.classificacao._replan_if_untouched(*a, **kw),
        perguntar_registrando=s.agent_task._perguntar_registrando,
    )
    # Reclassificação da demanda, replanejamento e duplicação (passo 11d).
    s.classificacao = ClassificationService(store, intake=s.intake)
    # Aprendizado, recomendação e próximo passo (passo 11d).
    s.insights = InsightService(
        store,
        repository=c.repo,
        routing_rules=c.routing_rules,
        execution=s.execution,
        settings=s.settings,
    )
    return s
