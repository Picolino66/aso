"""OrchestrationService (Control Plane).

Amarra os planes do runtime: cria orquestrações, gera ExecutionPlan, monta o
OrchestratorContext, o board Kanban e os cards, executa agentes (mock), submete
patches ao ContextBus, roda quality gate e gera snapshot. É o ponto de entrada
usado por API e CLI.
"""

from __future__ import annotations

import os
import shlex
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aso.agents.executor import AgentExecutionError, ExecutionProvider, LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.agents.registry import AgentRegistry
from aso.agents.supervisor import AgentSupervisor
from aso.control.decision_engine import MultiAgentDecisionEngine
from aso.control.deploy import (
    ACEITE_AGUARDANDO_HUMANO,
    ACEITE_APROVADO,
    ACEITE_REPROVADO,
    STATUS_FALHOU,
    STATUS_REVERTIDO,
    STATUS_SUCESSO,
    VALIDACAO_APROVADA,
    VALIDACAO_REPROVADA,
    DeployRun,
    executar_deploy,
    exige_aceite_humano,
    validar_pos_deploy,
)
from aso.control.discovery import (
    STATUS_AGUARDANDO_APROVACAO,
    STATUS_APROVADO,
    STATUS_REPROVADO,
    DiscoveryReport,
    DiscoveryService,
    exige_aprovacao_discovery,
)
from aso.control.documentos import acrescentar_versao, proxima_versao, versao_atual
from aso.control.execution_planner import ExecutionPlanner
from aso.control.failure import (
    ACAO_AUMENTAR_EFFORT,
    ACAO_BLOQUEAR,
    ACAO_ESCALAR_HUMANO,
    ACAO_MESMO_AGENTE,
    ACAO_TROCAR_EXECUTOR,
    ETAPA_CI,
    ETAPA_EXECUCAO,
    ETAPA_GATE,
    ETAPA_QA,
    DecisaoDeFalha,
    FailureRecord,
    decidir,
    diagnosticar,
    registrar,
)
from aso.control.models import (
    DISCOVERY_KEY,
    NAMING_KEY,
    REVIEW_KEY,
    SPEC_KEY,
    TRIAGE_KEY,
    AgentAssignment,
    DecisionInput,
    ExecutionPlan,
    Orchestration,
    PlannedAgent,
    Project,
    ProjectEvent,
    ValidationCheck,
)
from aso.control.naming import NamingService
from aso.control.next_step import NextStepInput, NextStepReport, compute_next_step
from aso.control.orcamento import SITUACAO_ESTOURADO, avaliar_orcamento
from aso.control.project_service import ProjectService
from aso.control.qa import (
    STATUS_FALHOU as QA_STATUS_FALHOU,
)
from aso.control.qa import (
    STATUS_PENDENTE as QA_STATUS_PENDENTE,
)
from aso.control.qa import (
    QaCheck,
)
from aso.control.review import (
    VEREDITO_ALTERACOES_OBRIGATORIAS,
    VEREDITO_APROVADO,
    VEREDITO_APROVADO_COM_SUGESTOES,
    VEREDITO_DOC_REPROVADO,
    VEREDITO_REPROVADO,
    ReviewService,
    ReviewVerdict,
    exige_confirmacao_humana,
)
from aso.control.selecao import resolver_topo, sugerir_effort
from aso.control.spec import (
    STATUS_AGUARDANDO_REVISAO as SPEC_STATUS_AGUARDANDO_REVISAO,
)
from aso.control.spec import (
    STATUS_APROVADO as SPEC_STATUS_APROVADO,
)
from aso.control.spec import (
    STATUS_APROVADOS as SPEC_STATUS_APROVADOS,
)
from aso.control.spec import (
    STATUS_NECESSITA_HUMANO as SPEC_STATUS_NECESSITA_HUMANO,
)
from aso.control.spec import (
    STATUS_REPROVADO as SPEC_STATUS_REPROVADO,
)
from aso.control.spec import (
    SpecDocument,
    SpecService,
    SpecWorkItem,
)
from aso.control.triage import DemandBrief, TriageService
from aso.control.validation import NOME_CHECK_LEGADO, checks_efetivos, sugerir_bateria
from aso.execution.candidates import CandidateRunner
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile, managed_codex_profiles
from aso.execution.cli_provider import TIMEOUT_PADRAO as CLI_AGENT_TIMEOUT_PADRAO
from aso.execution.codex_discovery import CodexDiscoveryError, discover_codex
from aso.execution.docs_drift import DocsDriftReport, check_drift
from aso.execution.docs_scaffold import write_scaffold
from aso.execution.gate_command import run_gate_command
from aso.execution.gate_validation import validate_gate_command
from aso.execution.settings_store import ExecutorSettingsStore
from aso.execution.workspace import (
    WorkspaceAnalyzer,
    WorkspaceError,
    WorkspaceReport,
    WorkspaceService,
)
from aso.execution.worktree import WorktreeError, WorktreeManager
from aso.governance.adr_registry import ADRRegistry
from aso.governance.context_store import OrchestratorContextStore
from aso.governance.contextbus import BusResult, ContextBus, PermissionPolicy
from aso.governance.models import (
    ADR,
    CandidateRun,
    Conflict,
    ContextPatch,
    HumanApproval,
    PullRequest,
    QualityGateResult,
    SloEvaluation,
    Snapshot,
)
from aso.governance.quality_gate_engine import Criterion, QualityGateEngine
from aso.governance.snapshot_engine import SnapshotEngine
from aso.kanban.board_service import BoardService
from aso.kanban.models import Board, KanbanCard
from aso.observability.agent_log import AgentLogBus
from aso.observability.aprendizado import (
    CardSnapshot,
    PullRequestSnapshot,
    RelatorioDeAprendizado,
    consolidar,
)
from aso.observability.logging import get_logger
from aso.persistence.memory import InMemoryOrchestrationRepository, InMemoryProjectRepository
from aso.persistence.ports import OrchestrationRepository, ProjectRepository
from aso.persistence.state import OrchestrationState
from aso.shared.agent_usage import UsoDoAgente, acumular_uso
from aso.shared.cache import TTLCache
from aso.shared.events import DomainEvent, EventLog
from aso.shared.ids import now_iso
from aso.shared.types import (
    AssigneeType,
    CardType,
    ColumnKey,
    ConflictType,
    ExecutionMode,
    GateStatus,
    PatchStatus,
    PatchType,
    Phase,
    RiskLevel,
)


def _section_delta(before: Any, after: Any) -> dict[str, list[str]]:
    """Delta semântico entre dois valores de uma seção: chaves add/removidas/alteradas.

    Para seções dicionário compara as chaves; para valores atômicos (ou ausência de um
    lado) reporta a própria seção como adicionada/removida/modificada. Puro (sem efeito).
    """
    if isinstance(before, dict) and isinstance(after, dict):
        ka, kb = set(before), set(after)
        return {
            "added": sorted(kb - ka),
            "removed": sorted(ka - kb),
            "modified": sorted(k for k in ka & kb if before.get(k) != after.get(k)),
        }
    has_before, has_after = before is not None, after is not None
    return {
        "added": [] if has_before else ["*"],
        "removed": [] if has_after else ["*"],
        "modified": ["*"] if has_before and has_after and before != after else [],
    }


def _drift_summary(rep: DocsDriftReport) -> str:
    """Resumo textual (pt-BR) do drift de docs para evidência do gate/UI."""
    partes: list[str] = []
    if rep.undocumented_modules:
        partes.append("módulos sem doc: " + ", ".join(rep.undocumented_modules))
    if rep.orphan_module_docs:
        partes.append("docs órfãs: " + ", ".join(rep.orphan_module_docs))
    if rep.broken_links:
        partes.append(f"{len(rep.broken_links)} link(s) quebrado(s)")
    if rep.unfilled_features:
        partes.append(f"{len(rep.unfilled_features)} doc(s) por preencher")
    return "; ".join(partes)


def _check_predicate(comando: str, repo: str) -> Callable[[dict[str, Any]], tuple[bool, str]]:
    """Fábrica do predicado de uma verificação da bateria (§12, ADR-0022).

    Fecha `comando`/`repo` por parâmetro da fábrica, não por variável de laço: é a
    forma de evitar a armadilha clássica de closure em `for` (§4.2/§5 do
    plano5.md) sem depender de default-arg em lambda, que o `mypy --strict` não
    consegue inferir contra o tipo `Predicate`.
    """

    def predicate(_c: dict[str, Any]) -> tuple[bool, str]:
        return run_gate_command(shlex.split(comando), repo)

    return predicate


def _docs_sync_check(root: str) -> tuple[bool, str]:
    """Predicado (não-bloqueante) do gate F5/F6: docs-first em sincronia com o código?"""
    try:
        rep = check_drift(root)
    except ValueError:
        return True, "sem pasta para checar docs"
    if not rep.has_docs:
        return True, "docs-first ainda não gerada"
    if not rep.has_drift:
        return True, "docs em sincronia com o código"
    return False, "drift de docs — " + _drift_summary(rep)


def _phase_for_agent(agent: str) -> Phase:
    """Mapeia um agente ao papel/fase típica da esteira (heurística por nome).

    Sem isto, com a esteira começando em F1, cards de desenvolvimento/QA cairiam em
    F1. O planejamento LLM (/plan) pode sobrescrever isso com fases explícitas.
    """
    name = agent.lower()
    if any(k in name for k in ("architect", "arquitet", "systemdesign", "security")):
        return Phase.F2
    if any(k in name for k in ("data", "api", "contract", "contrato")):
        return Phase.F3
    if any(k in name for k in ("ux", "ui", "planning", "planejamento", "backlog")):
        return Phase.F4
    if any(k in name for k in ("review", "qa", "test", "quality", "deploy", "doc")):
        return Phase.F6
    if any(k in name for k in ("observability", "incident", "operate", "operacao")):
        return Phase.F7
    if any(k in name for k in ("discovery", "market", "persona", "requirement", "requisito")):
        return Phase.F1
    return Phase.F5  # desenvolvimento (backend/frontend/mobile) como padrão


def _catalog_name_of(provider: ExecutionProvider | None) -> str:
    """Nome do perfil no catálogo a partir de `provider.id` (ADR-0019).

    `CliAgentExecutionProvider.id` já é o nome do perfil; `LlmExecutionProvider` usa
    `llm:<nome>` — sem remover o prefixo, `ExecutorCatalog.get()` nunca encontraria o
    perfil ao decidir `trocar_executor`/`aumentar_effort`.
    """
    if provider is None:
        return ""
    return str(getattr(provider, "id", "") or "").removeprefix("llm:")


def prioridade_de(brief: DemandBrief) -> RiskLevel:
    """A prioridade do card acompanha o risco da demanda — hoje ela é sempre MEDIUM.

    `DemandBrief.risco` já usa `RiskLevel`, o mesmo tipo de `KanbanCard.priority`.
    """
    return brief.risco


def _tipo_de_card(valor: str) -> CardType:
    """Converte o `tipo`/`type` de um item de plano/spec num `CardType` (§7,
    ADR-0025) — valor desconhecido cai em `TASK`, o mesmo comportamento que todo
    caminho de criação de card tinha antes desta ADR."""
    try:
        return CardType(valor)
    except ValueError:
        return CardType.TASK


# Ring de verificações de QA por card (§16, ADR-0025) — mesmo raciocínio de
# `_max_races_per_card`/ring de discovery/spec: histórico limitado, não ilimitado.
_QA_RING = 10

_GRAVIDADE_PARA_PRIORIDADE: dict[str, RiskLevel] = {
    "baixa": RiskLevel.LOW,
    "media": RiskLevel.MEDIUM,
    "alta": RiskLevel.HIGH,
    "critica": RiskLevel.CRITICAL,
}


def _descricao_bug_de_qa(check: QaCheck) -> str:
    """Monta a descrição do bug do §17 a partir do `QaCheck` reprovado — como
    reproduzir, ambiente, evidências, resultado atual e esperado, gravidade."""
    linhas = [f"Cenário: {check.cenario}"]
    if check.ambiente:
        linhas.append(f"Ambiente: {check.ambiente}")
    if check.passos:
        passos = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(check.passos))
        linhas.append(f"Como reproduzir:\n{passos}")
    if check.resultado_esperado:
        linhas.append(f"Resultado esperado: {check.resultado_esperado}")
    if check.resultado_obtido:
        linhas.append(f"Resultado obtido: {check.resultado_obtido}")
    if check.evidencias:
        linhas.append("Evidências: " + "; ".join(check.evidencias))
    linhas.append(f"Gravidade: {check.gravidade}")
    return "\n".join(linhas)


def _uso_do_output(output: AgentOutput | None) -> UsoDoAgente:
    """Lê o consumo que `CliAgentExecutionProvider` deixou em `artifacts["uso"]`
    (§1.1, ADR-0026) — provider mock/legado sem esta chave cai no default
    `origem="indisponivel"`, sem quebrar nenhum executor existente."""
    if output is None:
        return UsoDoAgente()
    bruto = output.artifacts.get("uso")
    if not isinstance(bruto, dict):
        return UsoDoAgente()
    try:
        return UsoDoAgente(**bruto)
    except TypeError:
        return UsoDoAgente()


def _tempo_ms_por_card(events: list[DomainEvent]) -> dict[str, float]:
    """Soma `AgentExecuted.ms` por card — insumo de "tempo gasto" do §24."""
    tempos: dict[str, float] = {}
    for e in events:
        if e.type != "AgentExecuted":
            continue
        card_id = e.payload.get("card_id")
        ms = e.payload.get("ms")
        if isinstance(card_id, str) and isinstance(ms, int | float):
            tempos[card_id] = tempos.get(card_id, 0.0) + float(ms)
    return tempos


@dataclass
class OrchestrationBundle:
    """Agrega o estado e os serviços de uma orquestração."""

    orchestration: Orchestration
    event_log: EventLog
    agent_registry: AgentRegistry
    store: OrchestratorContextStore
    adr_registry: ADRRegistry
    bus: ContextBus
    gate_engine: QualityGateEngine
    snapshot_engine: SnapshotEngine
    board_service: BoardService
    board: Board
    plan: ExecutionPlan
    snapshots: list[Snapshot] = field(default_factory=list)
    gate_results: list[QualityGateResult] = field(default_factory=list)
    approvals: list[HumanApproval] = field(default_factory=list)
    pull_requests: list[PullRequest] = field(default_factory=list)
    candidate_runs: list[CandidateRun] = field(default_factory=list)
    slo_evaluations: list[SloEvaluation] = field(default_factory=list)


# Domínio (ficha da demanda / spec) → agente do registro. Reaproveitado por
# `populate_from_plan` (backlog do LLM, M2) e `_materialize_spec_cards` (itens de
# trabalho da especificação, §5/§7/§10 do fluxo.md, ADR-0021) — mesmo vocabulário.
_DOMAIN_AGENTS: dict[str, str] = {
    "backend": "BackendDevelopmentAgent",
    "frontend": "FrontendDevelopmentAgent",
    "architecture": "ArchitectureDesignAgent",
    "contract": "DataApiContractsAgent",
    "database": "DatabaseAgent",
    "tests": "TestingAgent",
    "qa": "TestingAgent",
    "docs": "DocumentationAgent",
    "devops": "DevOpsAgent",
    "security": "SecurityAgent",
}


def _build_card_closure(
    b: OrchestrationBundle, card: KanbanCard, pr: PullRequest
) -> dict[str, Any]:
    """Ficha de encerramento do card (§23 do fluxo.md, ADR-0021) — preenchida no
    merge, o ponto em que o card chega a Done. Só registra o que o runtime já tem à
    mão: campo sem dado disponível (data de implantação, commits individuais) fica de
    fora — ficha com campo inventado é pior que ficha curta."""
    acoes = pr.review_verdict.get("acoes") if pr.review_verdict else []
    riscos_residuais = [
        str(a.get("descricao", "")) for a in (acoes or []) if a.get("severidade") == "sugestao"
    ]
    documentos: dict[str, int] = {}
    if b.orchestration.discovery_reports:
        documentos["discovery_versao"] = versao_atual(
            b.orchestration.discovery_reports, DiscoveryReport
        ).versao
    if b.orchestration.spec_documents:
        documentos["spec_versao"] = versao_atual(
            b.orchestration.spec_documents, SpecDocument
        ).versao
    return {
        "resumo": pr.title or card.title,
        "executor": card.executor or "",
        "revisor": pr.reviewed_by,
        "branch": pr.branch,
        "pr_id": pr.id,
        "rodadas_revisao": pr.review_rounds,
        "documentos": documentos,
        "evidencias": [f"CI: {pr.ci_status}", f"Revisão: {pr.review_status}"],
        "riscos_residuais": riscos_residuais,
        # §23 pede "effort utilizado"; custo real (§1.1, ADR-0026) responde a mesma
        # pergunta em dinheiro. `card.uso` vazio (executor que nunca informou uso)
        # não aparece como zero — o campo some, ficha curta é melhor que inventada.
        **({"custo_usd": card.uso["custo_usd"]} if card.uso.get("custo_usd") else {}),
        **({"modelo": card.uso["modelo"]} if card.uso.get("modelo") else {}),
        "encerrado_em": now_iso(),
    }


class OrchestrationService:
    """Serviço in-memory de orquestrações (MVP-1, sem persistência)."""

    def __init__(
        self,
        provider: ExecutionProvider | None = None,
        repository: OrchestrationRepository | None = None,
        project_repository: ProjectRepository | None = None,
        *,
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
        self._bundles: dict[str, OrchestrationBundle] = {}
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
        # Limite de rodadas do ciclo de revisão documental (§6, ADR-0021): esgotado, a
        # decisão escala para humano — sem isto, dois agentes (autor/revisor) podem
        # girar indefinidamente queimando tokens.
        self._max_rodadas_doc = (
            max_rodadas_doc
            if max_rodadas_doc is not None
            else int(os.environ.get("ASO_MAX_RODADAS_DOC", "3"))
        )
        # Saída ao vivo dos agentes CLI (ADR-0015): ring em memória, lido por polling.
        self._log_bus = log_bus or AgentLogBus()
        self._executor_store = executor_store  # persiste perfis (sem secrets)
        self._repo: OrchestrationRepository = repository or InMemoryOrchestrationRepository()
        self._projects = ProjectService(project_repository or InMemoryProjectRepository())
        self._read_cache = TTLCache(ttl_seconds=1.0)  # cache de leitura para agregações
        self._codex_cache = TTLCache(ttl_seconds=60.0)
        self._codex_lock = threading.Lock()
        # Retenção de corridas por card: evita o candidate_runs crescer sem limite.
        self._max_races_per_card = (
            max_races_per_card
            if max_races_per_card is not None
            else int(os.environ.get("ASO_MAX_RACES_PER_CARD", "20"))
        )
        # Retenção de amostras de SLO: evita slo_evaluations crescer sem limite.
        self._max_slo_samples = (
            max_slo_samples
            if max_slo_samples is not None
            else int(os.environ.get("ASO_MAX_SLO_SAMPLES", "200"))
        )
        # Limite duro do roteamento de falha (§13, ADR-0019): esgotado, a ação é sempre
        # escalar para humano — nunca deixa o laço de retry de `run_card` aberto.
        self._max_escalonamentos = (
            max_escalonamentos
            if max_escalonamentos is not None
            else int(os.environ.get("ASO_MAX_ESCALONAMENTOS", "3"))
        )
        # Escolha automática de esforço (§9 do fluxo.md, ADR-0022): liga por padrão —
        # a sugestão só preenche o vazio abaixo de toda escolha humana (§4.6), então é
        # seguro deixar ligado; `ASO_EFFORT_AUTOMATICO=0` restaura o comportamento
        # anterior (effort sempre cai no default do perfil do executor).
        self._effort_automatico = (
            effort_automatico
            if effort_automatico is not None
            else os.environ.get("ASO_EFFORT_AUTOMATICO", "1") != "0"
        )
        # Orçamento com freio (§1.2/§3.2, ADR-0026): default de orquestrações NOVAS.
        # Sem a env, `None` — nenhum teto, comportamento idêntico a antes deste
        # incremento (opt-in, não uma trava nova imposta a toda orquestração).
        env_orcamento = os.environ.get("ASO_ORCAMENTO_PADRAO_USD")
        self._orcamento_padrao_usd = float(env_orcamento) if env_orcamento else None
        # Locks por orquestração: serializam ler-bundle → mutar → persistir sob
        # requisições concorrentes (API/CLI multithread) — evita lost-update e
        # dupla hidratação (achados de concorrência 1.1/4.1). RLock = reentrante.
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._log = get_logger()  # eventos de domínio visíveis no stdout

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._locks.get(orchestration_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[orchestration_id] = lock
            return lock

    # ------------------------------------------------------------------ criação
    def create_orchestration(
        self,
        user_request: str,
        *,
        project_id: str | None = None,
        target_path: str | None = None,
        execution_mode: ExecutionMode = ExecutionMode.FULL_PIPELINE,
        executor: str | None = None,
        effort: str | None = None,
        validation_command: str | None = None,
        seed_cards: bool = True,
        decision_input: DecisionInput | None = None,
        demand_brief: DemandBrief | None = None,
    ) -> Orchestration:
        if executor is not None and self._catalog is not None:
            self._validate_executor(executor, effort)
        if validation_command is not None:
            validation_command = validate_gate_command(validation_command)
        if project_id is not None:
            target_path = self._projects.resolve_workspace(project_id, target_path)
        brief = demand_brief or DemandBrief()
        orchestration = Orchestration(
            project_id=project_id,
            target_path=target_path,
            execution_mode=execution_mode,
            user_request=user_request,
            selected_executor=executor,
            selected_effort=effort,
            demand_brief=brief.model_dump(mode="json") if demand_brief is not None else {},
            validation_command=validation_command,
            current_phase=Phase.F5 if execution_mode == ExecutionMode.CODE_EXECUTION else Phase.F1,
            orcamento_usd=self._orcamento_padrao_usd,
        )
        oid = orchestration.id
        events = EventLog()

        registry = AgentRegistry()
        registry.seed_defaults()

        store = OrchestratorContextStore(oid)
        adr_registry = ADRRegistry(oid)
        bus = ContextBus(
            store,
            permissions=PermissionPolicy(registry.permission_map()),
            adr_registry=adr_registry,
            event_log=events,
        )
        gate_engine = QualityGateEngine(event_log=events)
        snapshot_engine = SnapshotEngine(event_log=events)
        board_service = BoardService(event_log=events)
        board = board_service.create_board(oid, f"Board — {user_request[:40]}", project_id)

        # Plano de execução a partir da decisão multiagente.
        planner = ExecutionPlanner(MultiAgentDecisionEngine())
        din = decision_input or DecisionInput(user_request=user_request, domains=["backend"])
        plan = planner.plan(oid, execution_mode, din)

        # Registra a decisão de estratégia como ADR (rastreabilidade §21).
        adr_registry.create(
            title=f"Estratégia de execução: {plan.strategy.value}",
            decision=plan.reason,
            phase=orchestration.current_phase,
            context=f"Demanda: {user_request}",
            rationale="Decisão do MultiAgentDecisionEngine (§14).",
        )

        # Cria um card por agente planejado, na fase adequada ao papel do agente
        # (a esteira começa em F1; sem isso, cards de dev cairiam em F1).
        planned_cards: list[tuple[PlannedAgent, KanbanCard]] = []
        for planned in plan.agents:
            if not seed_cards:
                continue
            card = KanbanCard(
                board_id=board.id,
                orchestration_id=oid,
                phase=_phase_for_agent(planned.agent),
                type=CardType.TASK,
                title=f"{planned.agent}: {planned.reason or planned.role}",
                priority=prioridade_de(brief),
                assignee_type=AssigneeType.AGENT,
                assignee=planned.agent,
                status=ColumnKey.READY,
                acceptance_criteria=["Output do agente aplicado via ContextBus"],
            )
            planned_cards.append((planned, card))
        # Segunda passada: `dependencies` (§10 do fluxo.md) referencia IDs de cards
        # irmãos, que só existem depois que todos os cards desta onda nasceram.
        # Dependência apontando para um agente fora do plano é ignorada — ele não
        # participou desta estratégia (ex.: descartado pelo MultiAgentDecisionEngine).
        id_por_agente = {planned.agent: card.id for planned, card in planned_cards}
        for planned, card in planned_cards:
            card.dependencies = [
                id_por_agente[dep] for dep in planned.depends_on if dep in id_por_agente
            ]
            board_service.add_card(card)

        events.append(
            "OrchestrationCreated",
            {"orchestration_id": oid, "strategy": plan.strategy.value, "cards": len(plan.agents)},
        )

        bundle = OrchestrationBundle(
            orchestration=orchestration,
            event_log=events,
            agent_registry=registry,
            store=store,
            adr_registry=adr_registry,
            bus=bus,
            gate_engine=gate_engine,
            snapshot_engine=snapshot_engine,
            board_service=board_service,
            board=board,
            plan=plan,
        )
        # Ação crítica: registra aprovação humana pendente (§8.6/§24).
        if plan.requires_human_approval:
            bundle.approvals.append(
                HumanApproval(
                    orchestration_id=oid,
                    action=f"Executar estratégia {plan.strategy.value}",
                    risk=plan.risk_level.value,
                    reason=plan.reason,
                )
            )
            events.append("ApprovalRequested", {"orchestration_id": oid})

        self._bundles[oid] = bundle
        self._persist(bundle)
        return orchestration

    def populate_from_plan(self, orchestration_id: str, plan: Any) -> dict[str, object]:
        """Materializa um ProjectPlan (LLM) no board: cards concretos + ADRs (M2).

        Recebe um `ProjectPlan` (control.planning). Cria um card por item do backlog
        e registra as ADRs propostas — sob o lock por orquestração e persistido.
        Não passa pelo ContextBus (espelha create_orchestration, que cria cards/ADRs
        diretamente); os cards nascem em Ready, prontos para execução governada.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            for adr in plan.adrs:
                b.adr_registry.create(
                    title=adr.title,
                    decision=adr.decision,
                    phase=b.orchestration.current_phase,
                    context=f"Plano LLM para: {b.orchestration.user_request}",
                    rationale=adr.rationale,
                )
            created: list[str] = []
            planned_cards: list[tuple[Any, KanbanCard]] = []
            for item in plan.backlog:
                try:
                    phase = Phase(item.phase)
                except ValueError:
                    phase = Phase.F5
                assignee = _DOMAIN_AGENTS.get(item.domain, item.domain)
                if b.agent_registry.get(assignee) is None:
                    raise ValueError(f"Domínio/agente desconhecido no plano: {item.domain}")
                card = KanbanCard(
                    board_id=b.board.id,
                    orchestration_id=orchestration_id,
                    phase=phase,
                    type=_tipo_de_card(item.type),
                    title=item.title,
                    priority=prioridade_de(brief),
                    assignee_type=AssigneeType.AGENT,
                    assignee=assignee,
                    status=ColumnKey.READY,
                    acceptance_criteria=list(item.acceptance_criteria),
                )
                planned_cards.append((item, card))
            # Segunda passada: `depends_on` (§7/§10 do fluxo.md) referencia TÍTULOS de
            # itens irmãos deste mesmo backlog, que só viram ids depois que todos os
            # cards nasceram — mesmo padrão de `PlannedAgent.depends_on` em
            # `create_orchestration`. Título desconhecido é descartado, não quebra.
            id_por_titulo = {item.title: card.id for item, card in planned_cards}
            for item, card in planned_cards:
                card.dependencies = [
                    id_por_titulo[dep] for dep in item.depends_on if dep in id_por_titulo
                ]
                b.board_service.add_card(card)
                created.append(card.id)
            b.event_log.append(
                "PlanPopulated",
                {"cards": len(created), "adrs": len(plan.adrs), "product": plan.product.name},
            )
            self._persist(b)
            return {
                "orchestration_id": orchestration_id,
                "cards_created": created,
                "adrs_created": len(plan.adrs),
                "product": plan.product.model_dump(),
            }

    # -------------------------------------------------------------- persistência
    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        bundle = self._bundles.get(orchestration_id)
        if bundle is not None:
            return bundle
        # Double-checked locking: sem isto, duas requisições concorrentes para uma
        # orquestração ainda não cacheada hidratam instâncias divergentes e a
        # segunda escrita sobrescreve a primeira (lost-update). Garante instância única.
        with self._lock_for(orchestration_id):
            bundle = self._bundles.get(orchestration_id)
            if bundle is not None:
                return bundle
            state = self._repo.load(orchestration_id)
            if state is None:
                raise KeyError(f"Orquestração inexistente: {orchestration_id}")
            bundle = self._hydrate(state)
            self._bundles[orchestration_id] = bundle
            return bundle

    def _to_state(self, b: OrchestrationBundle) -> OrchestrationState:
        return OrchestrationState(
            orchestration=b.orchestration,
            plan=b.plan,
            context_payload=b.store.get(),
            context_version=b.store.version,
            context_frozen=sorted(b.store.frozen_sections),
            context_history=[asdict(h) for h in b.store.history],
            adrs=b.adr_registry.list_all(),
            snapshots=list(b.snapshots),
            conflicts=list(b.bus.conflicts),
            gate_results=list(b.gate_results),
            approvals=list(b.approvals),
            patches=list(b.bus.patches),
            pull_requests=list(b.pull_requests),
            candidate_runs=list(b.candidate_runs),
            slo_evaluations=list(b.slo_evaluations),
            board=b.board,
            cards=b.board_service.cards_of(b.board.id),
            card_events=list(b.board_service.card_events),
            events=[
                {"type": e.type, "payload": e.payload, "created_at": e.created_at}
                for e in b.event_log.all()
            ],
        )

    def _persist(self, b: OrchestrationBundle) -> None:
        # Serializa a serialização+save por orquestração: `_to_state` lê todo o
        # bundle e o repositório grava níveis por FK; concorrência aqui gera estado
        # persistido inconsistente. RLock reentrante (o chamador pode já o deter).
        with self._lock_for(b.orchestration.id):
            self._repo.save(self._to_state(b))
            self._read_cache.clear()  # invalida agregações após escrita

    def _hydrate(self, state: OrchestrationState) -> OrchestrationBundle:
        oid = state.orchestration.id
        events = EventLog()
        events.seed(
            [
                DomainEvent(type=e["type"], payload=e["payload"], created_at=e["created_at"])
                for e in state.events
            ]
        )
        registry = AgentRegistry()
        registry.seed_defaults()

        store = OrchestratorContextStore(oid)
        store.hydrate(
            payload=state.context_payload,
            version=state.context_version,
            frozen_sections=state.context_frozen,
            history=state.context_history,
        )
        adr_registry = ADRRegistry(oid)
        adr_registry.hydrate(state.adrs)
        bus = ContextBus(
            store,
            permissions=PermissionPolicy(registry.permission_map()),
            adr_registry=adr_registry,
            event_log=events,
        )
        bus.conflicts = list(state.conflicts)
        bus.patches = list(state.patches)
        gate_engine = QualityGateEngine(event_log=events)
        snapshot_engine = SnapshotEngine(event_log=events)
        snapshot_engine.hydrate(state.snapshots)
        board_service = BoardService(event_log=events)
        board_service.hydrate([state.board], state.cards, state.card_events)

        return OrchestrationBundle(
            orchestration=state.orchestration,
            event_log=events,
            agent_registry=registry,
            store=store,
            adr_registry=adr_registry,
            bus=bus,
            gate_engine=gate_engine,
            snapshot_engine=snapshot_engine,
            board_service=board_service,
            board=state.board,
            plan=state.plan,
            snapshots=list(state.snapshots),
            gate_results=list(state.gate_results),
            approvals=list(state.approvals),
            pull_requests=list(state.pull_requests),
            candidate_runs=list(state.candidate_runs),
            slo_evaluations=list(state.slo_evaluations),
        )

    def get(self, orchestration_id: str) -> Orchestration:
        return self._bundle(orchestration_id).orchestration

    def list_all(self, *, project_id: str | None = None) -> list[Orchestration]:
        # Leitura leve: consulta a tabela de orquestrações, sem hidratar aggregates.
        return self._repo.list_orchestrations(project_id=project_id)[0]

    def list_orchestrations_page(
        self, *, page: int = 1, page_size: int = 50, project_id: str | None = None
    ) -> dict[str, object]:
        page = max(page, 1)
        items, total = self._repo.list_orchestrations(
            limit=page_size, offset=(page - 1) * page_size, project_id=project_id
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    # --------------------------------------------------------- catálogo de projetos
    def create_project(
        self, *, name: str, description: str, target_path: str, actor: str
    ) -> Project:
        return self._projects.create(
            name=name, description=description, target_path=target_path, actor=actor
        )

    def list_projects(self, *, include_archived: bool = False) -> list[Project]:
        return self._projects.list_projects(include_archived=include_archived)

    def get_project(self, project_id: str) -> Project:
        return self._projects.get(project_id)

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None,
        description: str | None,
        target_path: str | None,
        actor: str,
    ) -> Project:
        return self._projects.update(
            project_id,
            name=name,
            description=description,
            target_path=target_path,
            actor=actor,
        )

    def archive_project(self, project_id: str, *, actor: str) -> Project:
        return self._projects.archive(project_id, actor=actor)

    def restore_project(
        self, project_id: str, *, actor: str, target_path: str | None = None
    ) -> Project:
        return self._projects.restore(project_id, actor=actor, target_path=target_path)

    def project_events(self, project_id: str) -> list[ProjectEvent]:
        return self._projects.events(project_id)

    def aggregate_metrics(self) -> dict[str, object]:
        cached = self._read_cache.get("aggregate")
        if cached is not None:
            return cached  # type: ignore[no-any-return]
        data = self._repo.aggregate_metrics()
        self._read_cache.set("aggregate", data)
        return data

    def get_context(self, orchestration_id: str) -> dict[str, object]:
        b = self._bundle(orchestration_id)
        return {
            "version": b.store.version,
            "context_hash": b.store.context_hash(),
            "payload": b.store.get(),
        }

    def get_plan(self, orchestration_id: str) -> ExecutionPlan:
        return self._bundle(orchestration_id).plan

    def get_cards(self, orchestration_id: str) -> list[KanbanCard]:
        b = self._bundle(orchestration_id)
        return b.board_service.cards_of(b.board.id)

    def list_adrs(self, orchestration_id: str) -> list[ADR]:
        return list(self._bundle(orchestration_id).adr_registry.list_all())

    def list_snapshots(self, orchestration_id: str) -> list[Snapshot]:
        return list(self._bundle(orchestration_id).snapshots)

    def timeline(self, orchestration_id: str) -> list[DomainEvent]:
        return self._bundle(orchestration_id).event_log.all()

    def conflicts(self, orchestration_id: str) -> list[Conflict]:
        return list(self._bundle(orchestration_id).bus.conflicts)

    _RESOLUTIONS = {
        ConflictType.ARCHITECTURE: "Criar ADR de override e referenciá-la em linked_adrs.",
        ConflictType.SNAPSHOT_LOCK: "Criar ADR de override para alterar a seção congelada.",
        ConflictType.CONTRACT: "Criar nova versão de API em vez de alterar/remover o contrato.",
        ConflictType.TOOL_PERMISSION: "Ajustar permissões ou reatribuir o agente.",
    }

    def _propose_resolution(
        self, b: OrchestrationBundle, conflict: Conflict, *, auto: bool = False
    ) -> None:
        """ConflictResolutionAgent (§15.15): escala o conflito e cria card ADRTask."""
        suggestion = self._RESOLUTIONS.get(conflict.type, "Escalar para resolução humana.")
        conflict.resolution = suggestion
        conflict.status = "escalated"
        b.board_service.add_card(
            KanbanCard(
                board_id=b.board.id,
                orchestration_id=b.orchestration.id,
                phase=b.orchestration.current_phase,
                type=CardType.ADR_TASK,
                title=f"Resolver conflito {conflict.type.value}",
                description=suggestion,
                status=ColumnKey.READY,
                assignee_type=AssigneeType.AGENT,
                assignee="ConflictResolutionAgent",
            )
        )
        b.event_log.append(
            "ConflictResolutionProposed",
            {"conflict_id": conflict.id, "type": conflict.type.value, "auto": auto},
        )

    def resolve_conflict(self, orchestration_id: str, conflict_id: str) -> Conflict:
        b = self._bundle(orchestration_id)
        conflict = next((c for c in b.bus.conflicts if c.id == conflict_id), None)
        if conflict is None:
            raise KeyError(f"Conflito inexistente: {conflict_id}")
        self._propose_resolution(b, conflict)
        self._persist(b)
        return conflict

    # ------------------------------------------------- Pull Requests (§26, MVP-4)
    def open_pr(
        self, orchestration_id: str, card_id: str, *, branch: str | None = None, title: str = ""
    ) -> PullRequest:
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        selected_branch = branch or card.branch
        if not selected_branch and b.orchestration.validation_command:
            raise ValueError("Card sem branch candidata para abrir PR.")
        if not selected_branch:
            selected_branch = f"aso/{card_id}"  # compatibilidade com o provider mock legado
        if (
            b.orchestration.validation_command
            and not self._workspace_for(b).branch_diff(selected_branch).strip()
        ):
            raise ValueError("Não é possível abrir PR sem alterações na branch candidata.")
        pr = PullRequest(
            orchestration_id=orchestration_id,
            card_id=card_id,
            branch=selected_branch,
            title=title or card.title,
        )
        b.pull_requests.append(pr)
        b.board_service.apply_event(card_id, "PROpened")  # → Review
        b.event_log.append("PROpened", {"pr_id": pr.id, "branch": pr.branch, "card_id": card_id})
        self._persist(b)
        return pr

    def _find_pr(self, b: OrchestrationBundle, pr_id: str) -> PullRequest:
        pr = next((p for p in b.pull_requests if p.id == pr_id), None)
        if pr is None:
            raise KeyError(f"PR inexistente: {pr_id}")
        return pr

    def report_ci(self, orchestration_id: str, pr_id: str, status: str) -> PullRequest:
        """CI reprovada é corrigível: o card volta para `NeedsFix` com o motivo no
        nudge da próxima tentativa (§13 do fluxo.md, ADR-0019) — distinto de `Failed`,
        reservado ao roteamento de execução que decidiu escalar para humano."""
        b = self._bundle(orchestration_id)
        pr = self._find_pr(b, pr_id)
        pr.ci_status = status
        if status == "failed" and pr.card_id:
            card = b.board_service.get_card(pr.card_id)
            if card is not None:
                record = FailureRecord(
                    etapa=ETAPA_CI,
                    tentativa=len(card.failures) + 1,
                    comando=pr.branch,
                    mensagem=f"CI reprovada na branch {pr.branch}",
                    executor=card.executor or "",
                )
                card.failures = registrar(card.failures, record)
                card.correction_actions = [
                    "A CI reprovou na tentativa anterior — corrija o que a validação "
                    "apontou antes de reenviar."
                ]
                b.board_service.apply_event(pr.card_id, "CIFailed")  # → NeedsFix
        b.event_log.append("CIReported", {"pr_id": pr_id, "status": status})
        self._persist(b)
        return pr

    def report_review(
        self,
        orchestration_id: str,
        pr_id: str,
        status: str,
        *,
        actor: str = "system",
        justificativa: str = "",
    ) -> PullRequest:
        """Registra o resultado da revisão — governado (ADR-0017).

        `status == "approved"` só é aceito com um veredito aprovado já registrado
        (via `run_review`) ou com `justificativa` humana não vazia (a rota exige
        papel admin nesse caso — a checagem fina é feita no handler da API). Sem
        nenhum dos dois, o clique que "aprovava" sem ninguém ter revisado deixa
        de existir.

        Risco alto (ou impacto sensível — `exige_confirmacao_humana`, §4/§14) não fecha
        com o veredito do agente sozinho, mesmo aprovado: a confirmação humana precisa
        ser uma decisão registrada (justificativa), não um clique (ADR-0019, pendência
        da ADR-0017 — sem isto, o gate de risco segurava em `pending` e qualquer
        `operator` soltava em seguida sem que `required_role` percebesse).
        """
        b = self._bundle(orchestration_id)
        pr = self._find_pr(b, pr_id)
        if status == "approved":
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            exige_humano = exige_confirmacao_humana(brief)
            veredito = pr.review_verdict.get("veredito") if pr.review_verdict else None
            veredito_aprovado = veredito in (VEREDITO_APROVADO, VEREDITO_APROVADO_COM_SUGESTOES)
            if (exige_humano or not veredito_aprovado) and not justificativa.strip():
                if not veredito_aprovado:
                    motivo = (
                        "Aprovação exige um veredito de revisão aprovado ou "
                        "justificativa humana (papel admin) — rode a revisão antes "
                        "de aprovar."
                    )
                else:
                    motivo = (
                        "O risco da demanda exige confirmação humana registrada: "
                        "aprove com justificativa (papel admin) mesmo com o veredito "
                        "do agente aprovado."
                    )
                raise ValueError(motivo)
            if pr.card_id:
                card = b.board_service.get_card(pr.card_id)
                if card is not None:
                    card.correction_actions = []
        pr.review_status = status
        if status == "changes_requested" and pr.card_id and b.board_service.get_card(pr.card_id):
            b.board_service.apply_event(pr.card_id, "ReviewRequestedChanges")  # → NeedsFix
        b.event_log.append(
            "ReviewReported",
            {"pr_id": pr_id, "status": status, "actor": actor, "justificativa": justificativa},
        )
        self._persist(b)
        return pr

    def _resolve_reviewer(
        self, b: OrchestrationBundle, *, origem_executor: str | None, explicit: str | None
    ) -> tuple[str | None, str]:
        """Resolve o executor revisor: explícito → etapa 'revisao' → default do
        catálogo — desde que DIFERENTE do executor que produziu o que está sendo
        revisado (código, §14; ou documento, §6, ADR-0021).

        Devolve `(executor, "")` quando resolvido, ou `(None, motivo)` quando não
        há revisor independente disponível — nunca aprova por omissão.
        """
        candidato = explicit
        if candidato is None:
            assignment = self._assignment(b, REVIEW_KEY)
            candidato = assignment.executor if assignment is not None else None
        if candidato is None and self._catalog is not None:
            candidato = self._catalog.default_name()
        if candidato is None:
            return None, "nenhum agente revisor configurado"
        if origem_executor is not None and candidato == origem_executor:
            return None, "revisor seria o mesmo executor que produziu o que está sendo revisado"
        return candidato, ""

    def get_review(self, orchestration_id: str, pr_id: str) -> ReviewVerdict:
        """Veredito completo da última revisão (vazio = ainda não revisada)."""
        b = self._bundle(orchestration_id)
        pr = self._find_pr(b, pr_id)
        if pr.review_verdict:
            return ReviewVerdict.model_validate(pr.review_verdict)
        return ReviewVerdict()

    def run_review(
        self,
        orchestration_id: str,
        pr_id: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
        actor: str = "system",
    ) -> PullRequest:
        """Roda o agente revisor sobre o diff real da PR e aplica o veredito (ADR-0017)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            pr = self._find_pr(b, pr_id)
            if not pr.card_id:
                raise ValueError("PR sem card associado: a revisão exige o card de origem.")
            card = b.board_service.get_card(pr.card_id)
            if card is None:
                raise KeyError(f"Card inexistente: {pr.card_id}")
            revisor, recusa = self._resolve_reviewer(
                b, origem_executor=card.executor, explicit=executor
            )
            if recusa:
                verdito = ReviewVerdict(fallback_reason=recusa)
            else:
                assert revisor is not None  # noqa: S101 - garantido por _resolve_reviewer
                assignment_ref = self._assignment(b, REVIEW_KEY)
                efetivo_effort = effort or (assignment_ref.effort if assignment_ref else None)
                assignment = AgentAssignment(executor=revisor, effort=efetivo_effort)
                diff = self._workspace_for(b).branch_diff(pr.branch)
                brief = DemandBrief.model_validate(b.orchestration.demand_brief)
                verdito = self._review.revisar(
                    assignment,
                    diff=diff,
                    card_title=card.title,
                    card_description=card.description,
                    acceptance_criteria=card.acceptance_criteria,
                    riscos=brief.riscos,
                )
            return self._apply_review_verdict(b, pr, card, verdito, actor=actor)

    def _apply_review_verdict(
        self,
        b: OrchestrationBundle,
        pr: PullRequest,
        card: KanbanCard,
        verdito: ReviewVerdict,
        *,
        actor: str,
    ) -> PullRequest:
        """Traduz o veredito em `review_status` (§4.3 da ADR-0017: risco decide se a
        aprovação do agente fecha sozinha) e move o card reprovado para NeedsFix."""
        brief = DemandBrief.model_validate(b.orchestration.demand_brief)
        pr.review_verdict = verdito.model_dump(mode="json")
        pr.reviewed_by = verdito.revisor
        pr.review_rounds += 1
        aprovado = verdito.veredito in (VEREDITO_APROVADO, VEREDITO_APROVADO_COM_SUGESTOES)
        reprovado = verdito.veredito in (VEREDITO_ALTERACOES_OBRIGATORIAS, VEREDITO_REPROVADO)
        if aprovado and not exige_confirmacao_humana(brief):
            pr.review_status = "approved"
            card.correction_actions = []
        elif reprovado:
            pr.review_status = "changes_requested"
            card.correction_actions = [
                acao.descricao for acao in verdito.acoes if acao.severidade == "obrigatoria"
            ]
            b.board_service.apply_event(card.id, "ReviewRequestedChanges")  # → NeedsFix
        else:  # aprovado que exige humano, ou necessita_humano
            pr.review_status = "pending"
        b.event_log.append(
            "ReviewRunCompleted",
            {
                "pr_id": pr.id,
                "actor": actor,
                "veredito": verdito.veredito,
                "origem": verdito.origem,
                "revisor": verdito.revisor,
                "review_status": pr.review_status,
            },
        )
        self._persist(b)
        return pr

    def merge_pr(self, orchestration_id: str, pr_id: str) -> PullRequest:
        """Merge governado: exige CI passed + review approved (§26A.6)."""
        # Lock por orquestração: o check-then-act (verifica status → muta → merge git)
        # precisa ser atômico para dois merges concorrentes não mesclarem em dobro.
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            pr = self._find_pr(b, pr_id)
            if pr.status != "open":
                raise ValueError(f"PR {pr_id} não está aberta (status={pr.status}).")
            if pr.ci_status != "passed" or pr.review_status != "approved":
                raise ValueError(
                    "Merge governado exige CI 'passed' e review 'approved' "
                    f"(ci={pr.ci_status}, review={pr.review_status})."
                )
            # Mensagem com o que foi entregue: `git log` da branch base precisa contar a
            # história sozinho, e "aso: merge governado" em todo merge não conta nada.
            titulo = (pr.title or "").strip()
            self._workspace_for(b).merge(
                pr.branch,
                message=f"aso: merge {pr.branch}" + (f" — {titulo}" if titulo else ""),
            )
            pr.status = "merged"
            pr.merged_at = now_iso()
            card = b.board_service.get_card(pr.card_id) if pr.card_id else None
            if card is not None and pr.card_id is not None:
                card.closure = _build_card_closure(b, card, pr)
                b.board_service.apply_event(pr.card_id, "QualityGatePassed")  # → Done
            b.event_log.append("PRMerged", {"pr_id": pr_id, "branch": pr.branch})
        self._log.info(
            "pr_merged", orchestration_id=orchestration_id, pr_id=pr_id, branch=pr.branch
        )
        self._persist(b)
        return pr

    # ------------------------------------------------------------------- QA (§16/§17)

    def register_qa_check(
        self,
        orchestration_id: str,
        card_id: str,
        *,
        cenario: str,
        passos: list[str] | None = None,
        ambiente: str = "",
        resultado_esperado: str = "",
        resultado_obtido: str = "",
        evidencias: list[str] | None = None,
        gravidade: str = "media",
        status: str = QA_STATUS_PENDENTE,
        tipo_responsavel: str = "humano",
        actor: str = "system",
    ) -> QaCheck:
        """Registra uma verificação manual de QA (§16) no ring do card (10 últimas)."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        check = QaCheck(
            cenario=cenario,
            passos=list(passos or []),
            ambiente=ambiente,
            resultado_esperado=resultado_esperado,
            resultado_obtido=resultado_obtido,
            evidencias=list(evidencias or []),
            gravidade=gravidade,
            status=status,
            responsavel=actor,
            tipo_responsavel=tipo_responsavel,
        )
        card.qa_checks = [*card.qa_checks, check.model_dump(mode="json")][-_QA_RING:]
        b.event_log.append(
            "QaCheckRegistered",
            {"card_id": card_id, "cenario": cenario, "status": status, "actor": actor},
        )
        self._persist(b)
        return check

    def get_qa_checks(self, orchestration_id: str, card_id: str) -> list[QaCheck]:
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        return [QaCheck.model_validate(c) for c in card.qa_checks]

    def fail_qa_check(
        self,
        orchestration_id: str,
        card_id: str,
        index: int,
        *,
        resultado_obtido: str = "",
        evidencias: list[str] | None = None,
        gravidade: str | None = None,
        actor: str = "system",
    ) -> KanbanCard:
        """§17: reprovação de QA cria um bug vinculado ao card original e devolve o
        card ao ponto certo do fluxo — via a mesma tabela de roteamento de falha
        (ADR-0019, `diagnosticar`/`decidir`), sem taxonomia nova."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        if not 0 <= index < len(card.qa_checks):
            raise KeyError(f"Verificação de QA inexistente: índice {index}")
        check = QaCheck.model_validate(card.qa_checks[index])
        check.status = QA_STATUS_FALHOU
        if resultado_obtido:
            check.resultado_obtido = resultado_obtido
        if evidencias:
            check.evidencias = list(evidencias)
        if gravidade:
            check.gravidade = gravidade
        card.qa_checks[index] = check.model_dump(mode="json")

        bug = self._criar_bug_de_qa(b, card, check)

        record = FailureRecord(
            etapa=ETAPA_QA,
            tentativa=len(card.failures) + 1,
            comando="qa",
            mensagem=f"QA reprovado: {check.cenario}",
            saida=check.resultado_obtido,
            categoria="qa",
        )
        card.failures = registrar(card.failures, record)
        diagnostico = diagnosticar(record)
        decisao = decidir(
            diagnostico,
            len(card.failures),
            catalogo=self._catalog,
            max_escalonamentos=self._max_escalonamentos,
        )
        card.correction_actions = [decisao.nudge] if decisao.nudge else []
        detalhe = f"QA reprovado: {check.cenario} — {decisao.motivo}"
        b.event_log.append(
            "QaCheckFailed",
            {
                "card_id": card_id,
                "cenario": check.cenario,
                "bug_id": bug.id,
                "diagnostico": diagnostico,
                "acao": decisao.acao,
                "actor": actor,
            },
        )
        destino = ColumnKey.FAILED if decisao.acao == ACAO_ESCALAR_HUMANO else ColumnKey.NEEDS_FIX
        b.board_service.move_card(
            card_id, destino, reason=detalhe, result="falhou", next_action=decisao.acao
        )
        self._persist(b)
        atualizado = b.board_service.get_card(card_id)
        assert atualizado is not None  # noqa: S101 - card acabou de ser lido/movido acima
        return atualizado

    def _criar_bug_de_qa(
        self, b: OrchestrationBundle, card: KanbanCard, check: QaCheck
    ) -> KanbanCard:
        """Cria o card `Bug` do §17, vinculado por `dependencies` (para o observador
        de `blocked_by` da ADR-0018/0022) e por `parent_id` quando a hierarquia (§7)
        permitir — card original já no nível mais profundo cai sem `parent_id`, a
        dependência sozinha já vincula."""
        bug = KanbanCard(
            board_id=b.board.id,
            orchestration_id=b.orchestration.id,
            phase=card.phase,
            type=CardType.BUG,
            title=f"QA reprovado: {check.cenario}"[:200],
            description=_descricao_bug_de_qa(check),
            priority=_GRAVIDADE_PARA_PRIORIDADE.get(check.gravidade, RiskLevel.MEDIUM),
            assignee_type=card.assignee_type,
            assignee=card.assignee,
            status=ColumnKey.BACKLOG,
            dependencies=[card.id],
            parent_id=card.id,
        )
        try:
            b.board_service.add_card(bug)
        except ValueError:
            bug.parent_id = None
            b.board_service.add_card(bug)
        b.event_log.append("BugCreatedFromQa", {"card_id": card.id, "bug_id": bug.id})
        return bug

    # ------------------------------------------------------------- aprendizado (§24)

    def _coletar_aprendizado(
        self, b: OrchestrationBundle
    ) -> tuple[list[CardSnapshot], list[PullRequestSnapshot], int]:
        """Coleta o estado já persistido do bundle e o achata para o agregador puro
        de `observability/aprendizado.py` — o único ponto que pode ligar `control`
        a `observability` (mesmo arranjo de `next_step`/`Service.next_step`)."""
        cards_do_board = b.board_service.cards_of(b.board.id)
        tempo_por_card = _tempo_ms_por_card(b.event_log.all())
        cards = [
            CardSnapshot(
                id=c.id,
                executor=c.executor or "",
                failures=list(c.failures),
                tempo_ms=tempo_por_card.get(c.id, 0.0),
                custo_usd=float(c.uso.get("custo_usd", 0.0)),
                # Nenhuma execução informou uso ainda (inclui card nunca executado,
                # 0 >= 0) — nunca "custou zero" por omissão (§1.1, ADR-0026).
                uso_indisponivel=int(c.uso.get("execucoes_sem_custo", 0))
                >= int(c.uso.get("execucoes", 0)),
                entregue=c.status == ColumnKey.DONE,
            )
            for c in cards_do_board
        ]
        pulls = [
            PullRequestSnapshot(
                card_id=pr.card_id, review_rounds=pr.review_rounds, review_status=pr.review_status
            )
            for pr in b.pull_requests
        ]
        intervencoes = sum(1 for a in b.approvals if a.status in ("approved", "rejected"))
        intervencoes += sum(
            1
            for c in cards_do_board
            for check in c.qa_checks
            if check.get("tipo_responsavel") == "humano"
            and check.get("status") in ("passou", "falhou")
        )
        return cards, pulls, intervencoes

    def get_learning_report(self, orchestration_id: str) -> RelatorioDeAprendizado:
        """Relatório de aprendizado de UMA demanda (§24) — retrabalho, falhas por
        etapa, desempenho por executor, intervenções humanas. Informativo: não
        altera nenhuma decisão automaticamente (§3.4 do plano6)."""
        b = self._bundle(orchestration_id)
        cards, pulls, intervencoes = self._coletar_aprendizado(b)
        return consolidar(orchestration_id, cards, pulls, intervencoes_humanas=intervencoes)

    def get_learning_report_global(self) -> RelatorioDeAprendizado:
        """Mesmo relatório, consolidado entre TODAS as orquestrações."""
        orchestrations, _ = self._repo.list_orchestrations()
        cards: list[CardSnapshot] = []
        pulls: list[PullRequestSnapshot] = []
        intervencoes = 0
        for orch in orchestrations:
            b = self._bundle(orch.id)
            c, p, i = self._coletar_aprendizado(b)
            cards.extend(c)
            pulls.extend(p)
            intervencoes += i
        return consolidar("todas", cards, pulls, intervencoes_humanas=intervencoes)

    def run_pr_ci(self, orchestration_id: str, pr_id: str) -> PullRequest:
        """Executa a validação configurada na branch candidata da PR."""
        b = self._bundle(orchestration_id)
        pr = self._find_pr(b, pr_id)
        command = b.orchestration.validation_command or os.environ.get("ASO_GATE_TEST_COMMAND")
        if not command:
            raise ValueError("Configure o comando de validação antes de rodar a CI.")
        ok, detail = self._workspace_for(b).run_on_branch(pr.branch, shlex.split(command))
        pr.ci_status = "passed" if ok else "failed"
        b.event_log.append("CIReported", {"pr_id": pr_id, "status": pr.ci_status, "detail": detail})
        self._persist(b)
        return pr

    def list_pulls(self, orchestration_id: str) -> list[PullRequest]:
        return list(self._bundle(orchestration_id).pull_requests)

    def race_card(
        self, orchestration_id: str, card_id: str, providers: list[ExecutionProvider]
    ) -> dict[str, object]:
        """Roda múltiplos agentes CLI em paralelo por card e compara os diffs (§26A.6)."""
        b = self._bundle(orchestration_id)
        self._recusar_se_orcamento_estourado(b)
        card = b.board_service.get_card(card_id)
        if card is None or card.assignee is None:
            raise KeyError(f"Card inválido: {card_id}")
        agent = b.agent_registry.get(card.assignee)
        if agent is None:
            raise KeyError(f"Agente não registrado: {card.assignee}")
        candidates = CandidateRunner().run(agent, self._build_task(b, card, agent), providers)
        comparison = CandidateRunner.compare(candidates)
        # Persiste a corrida como entidade rastreável (histórico auditável §26A.6/§21).
        run = CandidateRun(
            orchestration_id=orchestration_id,
            card_id=card_id,
            recommended_branch=comparison["recommended_branch"],
            candidates=list(comparison["candidates"]),
        )
        b.candidate_runs.append(run)
        self._prune_races(b, card_id)
        b.event_log.append(
            "CandidatesEvaluated",
            {
                "run_id": run.id,
                "card_id": card_id,
                "count": len(candidates),
                "recommended": comparison["recommended_branch"],
            },
        )
        # Candidato perdido nunca é silencioso (plano6 §0/ADR-0024): um evento por
        # falha, rastreável mesmo depois que o ring de corridas descartar `run`.
        falhas = comparison["falhas"]
        for falha in falhas:
            b.event_log.append(
                "CandidateFailed",
                {"run_id": run.id, "card_id": card_id, **falha},
            )
        self._persist(b)
        comparison["run_id"] = run.id
        return comparison

    def _prune_races(self, b: OrchestrationBundle, card_id: str) -> None:
        """Mantém apenas as N corridas mais recentes por card (retenção §26A.6)."""
        same = [r for r in b.candidate_runs if r.card_id == card_id]
        if len(same) <= self._max_races_per_card:
            return
        drop = {r.id for r in same[: len(same) - self._max_races_per_card]}
        b.candidate_runs[:] = [r for r in b.candidate_runs if r.id not in drop]

    def list_candidate_runs(
        self, orchestration_id: str, card_id: str | None = None
    ) -> list[CandidateRun]:
        """Histórico de corridas de candidatos (opcionalmente filtrado por card)."""
        runs = self._bundle(orchestration_id).candidate_runs
        if card_id:
            return [r for r in runs if r.card_id == card_id]
        return list(runs)

    # ---------------------------------------------------------- SLO (série temporal)
    def record_slo_evaluation(
        self, orchestration_id: str, evaluation: SloEvaluation
    ) -> SloEvaluation:
        """Persiste uma amostra de avaliação de SLO (série temporal de burn-rate, F7)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            b.slo_evaluations.append(evaluation)
            # Retenção: mantém apenas as N amostras mais recentes (ordem de inserção).
            if len(b.slo_evaluations) > self._max_slo_samples:
                del b.slo_evaluations[: len(b.slo_evaluations) - self._max_slo_samples]
            b.event_log.append(
                "SloEvaluated",
                {
                    "id": evaluation.id,
                    "burn_rate": evaluation.burn_rate,
                    "severity": evaluation.severity,
                },
            )
            self._persist(b)
            return evaluation

    def list_slo_evaluations(
        self, orchestration_id: str, *, limit: int | None = None
    ) -> list[SloEvaluation]:
        """Amostras de SLO em ordem cronológica (as `limit` mais recentes, se dado)."""
        evals = list(self._bundle(orchestration_id).slo_evaluations)
        return evals[-limit:] if limit else evals

    # ------------------------------------------------- context patches / auditoria
    def list_patches(self, orchestration_id: str, status: str | None = None) -> list[ContextPatch]:
        patches = self._bundle(orchestration_id).bus.patches
        if status:
            return [p for p in patches if p.status.value == status]
        return list(patches)

    def get_patch(self, orchestration_id: str, patch_id: str) -> ContextPatch | None:
        for patch in self._bundle(orchestration_id).bus.patches:
            if patch.id == patch_id:
                return patch
        return None

    def submit_patch(self, orchestration_id: str, patch: ContextPatch) -> BusResult:
        """Submete um ContextPatch ao ContextBus (§ POST /v1/context-patches)."""
        b = self._bundle(orchestration_id)
        result = self._submit_with_approval(b, patch)
        self._persist(b)
        return result

    def audit(self, orchestration_id: str) -> dict[str, object]:
        """Trilha de auditoria consolidada (eventos + patches + conflitos + approvals)."""
        b = self._bundle(orchestration_id)
        events = b.event_log.all()
        patches = b.bus.patches
        return {
            "orchestration_id": orchestration_id,
            "events_total": len(events),
            "patches_total": len(patches),
            "patches_applied": sum(1 for p in patches if p.status.value == "applied"),
            "patches_rejected": sum(1 for p in patches if p.status.value == "rejected"),
            "conflicts_total": len(b.bus.conflicts),
            "approvals_total": len(b.approvals),
            "events": [
                {"type": e.type, "payload": e.payload, "created_at": e.created_at} for e in events
            ],
        }

    # ------------------------------------------------------- F7: feedback → backlog
    def add_feedback(
        self, orchestration_id: str, text: str, *, card_type: str = "Improvement"
    ) -> KanbanCard:
        """Converte feedback em card de backlog (user-feedback-engine, §F7)."""
        b = self._bundle(orchestration_id)
        try:
            ctype = CardType(card_type)
        except ValueError:
            ctype = CardType.IMPROVEMENT
        card = KanbanCard(
            board_id=b.board.id,
            orchestration_id=orchestration_id,
            phase=b.orchestration.current_phase,
            type=ctype,
            title=f"Feedback: {text[:60]}",
            description=text,
            status=ColumnKey.BACKLOG,
            assignee_type=AssigneeType.HUMAN,
        )
        b.board_service.add_card(card)
        b.event_log.append("FeedbackReceived", {"card_id": card.id, "text": text})
        self._persist(b)
        return card

    # ------------------------------------------------- gates / conflitos / approvals
    def list_gate_results(self, orchestration_id: str) -> list[QualityGateResult]:
        return list(self._bundle(orchestration_id).gate_results)

    def find_gate_result(self, gate_id: str) -> QualityGateResult | None:
        for oid in self._repo.list_ids():
            for gate in self._bundle(oid).gate_results:
                if gate.id == gate_id:
                    return gate
        return None

    def request_approval(
        self,
        orchestration_id: str,
        action: str,
        *,
        risk: str = "medium",
        reason: str = "",
        card_id: str | None = None,
    ) -> HumanApproval:
        b = self._bundle(orchestration_id)
        approval = HumanApproval(
            orchestration_id=orchestration_id,
            card_id=card_id,
            action=action,
            risk=risk,
            reason=reason,
        )
        b.approvals.append(approval)
        b.event_log.append("ApprovalRequested", {"approval_id": approval.id, "action": action})
        self._persist(b)
        return approval

    def list_approvals(self, orchestration_id: str) -> list[HumanApproval]:
        return list(self._bundle(orchestration_id).approvals)

    def list_all_approvals(self) -> list[HumanApproval]:
        return [a for oid in self._repo.list_ids() for a in self._bundle(oid).approvals]

    def get_approval(self, approval_id: str) -> HumanApproval | None:
        found = self._find_approval(approval_id)
        return found[1] if found else None

    def decide_approval(
        self, approval_id: str, *, approved: bool, approved_by: str = "human"
    ) -> HumanApproval:
        found = self._find_approval(approval_id)
        if found is None:
            raise KeyError(f"Aprovação inexistente: {approval_id}")
        bundle, approval = found
        # Lock por orquestração: decidir + aplicar o patch pendente é check-then-act;
        # duas decisões concorrentes não podem aplicar o mesmo patch em dobro (§24).
        with self._lock_for(bundle.orchestration.id):
            approval.status = "approved" if approved else "rejected"
            approval.approved_by = approved_by
            # Se a aprovação está vinculada a um patch pendente, aplica-o agora (§24).
            patch_id = approval.payload.get("patch_id") if approved else None
            if patch_id:
                patch = next(
                    (
                        p
                        for p in bundle.bus.patches
                        if p.id == patch_id and p.status == PatchStatus.PENDING
                    ),
                    None,
                )
                if patch is not None:
                    bundle.bus.apply_approved(patch)
            # Libera/bloqueia o card vinculado no Kanban.
            if approval.card_id and bundle.board_service.get_card(approval.card_id) is not None:
                if approved:
                    bundle.board_service.apply_event(approval.card_id, "TestsPassed")
                else:
                    bundle.board_service.move_card(
                        approval.card_id, ColumnKey.BLOCKED, reason="aprovação rejeitada"
                    )
            bundle.event_log.append(
                "ApprovalDecided",
                {"approval_id": approval_id, "status": approval.status, "by": approved_by},
            )
            self._persist(bundle)
            # Autopilot (M4): aprovar um portão de fase avança e roda a próxima fase.
            is_phase_gate = approved and approval.payload.get("kind") == "phase_gate"
            autopilot_phase = approval.payload.get("phase") if is_phase_gate else None
            autopilot_executor = approval.payload.get("executor") if is_phase_gate else None
            autopilot_effort = approval.payload.get("effort") if is_phase_gate else None
        # Fora do lock do bundle: o encadeamento re-adquire o lock por orquestração.
        if autopilot_phase is not None:
            self._advance_after_phase_gate(
                bundle.orchestration.id,
                str(autopilot_phase),
                executor=autopilot_executor,
                effort=autopilot_effort,
            )
        return approval

    def _advance_after_phase_gate(
        self,
        orchestration_id: str,
        completed_phase: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
    ) -> None:
        """Auto-avanço do autopilot: fase aprovada → próxima fase roda sozinha (M4).

        Não recursa: `run_phase` da próxima fase abre uma NOVA aprovação pendente e
        para ali, aguardando o humano (pausa só na aprovação, como pedido).
        """
        try:
            nxt = self._next_phase(Phase(completed_phase))
        except ValueError:
            return
        if nxt is None:
            # Última fase aprovada → esteira concluída.
            with self._lock_for(orchestration_id):
                b = self._bundle(orchestration_id)
                b.orchestration.status = "completed"
                b.event_log.append("AutopilotCompleted", {"phase": completed_phase})
                self._persist(b)
            self._log.info(
                "autopilot_completed", orchestration_id=orchestration_id, phase=completed_phase
            )
            return
        self._log.info("autopilot_advanced", orchestration_id=orchestration_id, to=nxt.value)
        self.advance_phase(orchestration_id)
        # A escolha herdada da fase anterior só vale se a próxima etapa não tiver
        # executor próprio (ADR-0014) — senão a configuração por etapa nunca valeria
        # no autopilot, que é justamente onde ela mais importa.
        if self._assignment(self._bundle(orchestration_id), nxt.value) is not None:
            executor, effort = None, None
        self.run_phase(orchestration_id, nxt, executor=executor, effort=effort)

    def start_autopilot(
        self, orchestration_id: str, *, executor: str | None = None, effort: str | None = None
    ) -> dict[str, object]:
        """Dá partida no autopilot: roda a fase atual e abre a 1ª aprovação de avanço.

        `executor`/`effort` escolhem o agente e o esforço; a escolha se propaga a cada
        fase automaticamente via a aprovação (todo o pipeline usa o mesmo, salvo troca).
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            effective_executor = executor or b.orchestration.selected_executor
            effective_effort = effort or b.orchestration.selected_effort
            b.orchestration.selected_executor = effective_executor
            b.orchestration.selected_effort = effective_effort
            if not b.orchestration.workspace_prepared and b.orchestration.target_path:
                self.analyze_folder(
                    orchestration_id, executor=effective_executor, effort=effective_effort
                )
                b = self._bundle(orchestration_id)
                b.orchestration.workspace_prepared = True
            if b.orchestration.execution_mode == ExecutionMode.CODE_EXECUTION and not (
                b.orchestration.validation_command or os.environ.get("ASO_GATE_TEST_COMMAND")
            ):
                raise ValueError("Configure o comando de validação antes de executar código.")
            b.orchestration.status = "running"
            b.event_log.append("AutopilotStarted", {"phase": b.orchestration.current_phase.value})
            self._persist(b)
        return self.run_phase(
            orchestration_id, executor=effective_executor, effort=effective_effort
        )

    def _find_approval(self, approval_id: str) -> tuple[OrchestrationBundle, HumanApproval] | None:
        for oid in self._repo.list_ids():
            bundle = self._bundle(oid)
            for approval in bundle.approvals:
                if approval.id == approval_id:
                    return bundle, approval
        return None

    # ------------------------------------------------- ciclo de vida (§28.1)
    def rollback(self, orchestration_id: str, to_snapshot: str) -> Orchestration:
        b = self._bundle(orchestration_id)
        if b.snapshot_engine.get(to_snapshot) is None:
            raise KeyError(f"Snapshot inexistente: {to_snapshot}")
        b.snapshot_engine.restore(to_snapshot, b.store)
        b.orchestration.snapshot_version = to_snapshot
        b.orchestration.status = "running"
        b.adr_registry.create(
            title=f"Rollback para {to_snapshot}",
            decision=f"Contexto restaurado ao snapshot {to_snapshot}",
            phase=b.orchestration.current_phase,
            context="Rollback solicitado (protocolo de contexto).",
        )
        self._persist(b)
        return b.orchestration

    def cancel(self, orchestration_id: str) -> Orchestration:
        b = self._bundle(orchestration_id)
        b.orchestration.status = "cancelled"
        b.event_log.append("OrchestrationCancelled", {"orchestration_id": orchestration_id})
        self._persist(b)
        return b.orchestration

    def recover_invalid_execution(self, orchestration_id: str) -> Orchestration:
        """Invalida execuções históricas sem diff/exit válido e retorna à F5.

        É uma ação administrativa explícita: não reescreve patches nem snapshots;
        apenas fecha aprovações futuras e torna o card reexecutável sob as regras novas.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            invalid_cards = {
                patch.card_id
                for patch in b.bus.patches
                if patch.card_id
                and isinstance(patch.content, dict)
                and (patch.content.get("exit_code", 0) != 0 or patch.content.get("diff_lines") == 0)
            }
            if not invalid_cards:
                raise ValueError("Não há execução inválida para recuperar.")
            for card_id in invalid_cards:
                card = b.board_service.get_card(card_id)
                if card is not None:
                    b.board_service.move_card(
                        card_id, ColumnKey.FAILED, reason="Execução histórica sem diff válido"
                    )
            for approval in b.approvals:
                if approval.status == "pending" and approval.payload.get("kind") == "phase_gate":
                    approval.status = "cancelled"
            b.orchestration.current_phase = Phase.F5
            b.orchestration.status = "waiting_human"
            b.event_log.append(
                "InvalidExecutionRecovered", {"cards": sorted(invalid_cards), "phase": "F5"}
            )
            self._persist(b)
            return b.orchestration

    def resume(self, orchestration_id: str) -> Orchestration:
        b = self._bundle(orchestration_id)
        b.orchestration.status = "running"
        b.event_log.append("OrchestrationResumed", {"orchestration_id": orchestration_id})
        self._persist(b)
        return b.orchestration

    def retry(self, orchestration_id: str) -> list[str]:
        """Reexecuta cards pendentes/falhos (§28.1), respeitando o ponto certo (§13).

        Gate reprovado roteia só os cards da fase que ainda não chegaram a `Done` —
        não reinicia a fase inteira (Princípio central do fluxo.md: "retorna
        exatamente ao ponto responsável pelo erro"). Fora desse caso, cai na varredura
        genérica de cards prontos/falhos/bloqueados de sempre.
        """
        b = self._bundle(orchestration_id)
        targets = self._gate_retry_targets(b)
        if targets is None:
            retryable = {ColumnKey.READY, ColumnKey.FAILED, ColumnKey.BLOCKED}
            targets = [c.id for c in b.board_service.cards_of(b.board.id) if c.status in retryable]
        for card_id in targets:
            try:
                self.run_card(orchestration_id, card_id)
            except (KeyError, ValueError):
                # Card inválido ou com dependência ainda pendente: não derruba o resto
                # do retry — o `run_card` já registrou o motivo no próprio card.
                continue
        return targets

    def _gate_retry_targets(self, b: OrchestrationBundle) -> list[str] | None:
        """Cards da fase do último gate reprovado (se houver e ainda for o mais
        recente daquela fase) que ainda não chegaram a `Done`. `None` = não se aplica
        (cai na varredura genérica de `retry`).

        Desde a ADR-0022, a reprovação também passa pelo roteamento de falha (§13,
        ADR-0019): a verificação nomeada que reprovou primeiro dá `categoria` ao
        diagnóstico — fato, não heurística por palavra-chave (`diagnosticar` prefere
        a categoria quando ela existe). A escalada (effort maior/outro executor) é
        da ETAPA, não do card isolado: grava em `agent_assignments[fase]`, então a
        próxima chamada de `run_card` de qualquer card dessa fase já nasce com o
        degrau novo — sem isto, cada card escalaria isoladamente e do zero.
        """
        ultimo = b.gate_results[-1] if b.gate_results else None
        if ultimo is None or ultimo.status != GateStatus.FAILED:
            return None
        pendentes = [
            c
            for c in b.board_service.cards_of(b.board.id)
            if c.phase == ultimo.phase and c.status != ColumnKey.DONE
        ]
        if not pendentes:
            return None
        falhados = [
            c.failure_reason or c.name for c in ultimo.criteria if c.status == GateStatus.FAILED
        ]
        detalhe = " · ".join(ultimo.required_actions or ultimo.blocking_issues or falhados)
        categorias = {c.nome: c.categoria for c in checks_efetivos(b.orchestration)}
        nomes_falhados = ultimo.blocking_issues or [
            c.name for c in ultimo.criteria if c.status == GateStatus.FAILED
        ]
        primeiro_check = next((nome for nome in nomes_falhados if nome in categorias), "")
        categoria = categorias.get(primeiro_check, "")
        diagnostico = diagnosticar(FailureRecord(check=primeiro_check, categoria=categoria))
        tentativa_fase = sum(
            1 for g in b.gate_results if g.phase == ultimo.phase and g.status == GateStatus.FAILED
        )
        assignment_atual = b.orchestration.agent_assignments.get(ultimo.phase.value)
        executor_atual = (
            (assignment_atual.executor if assignment_atual else None)
            or self._effective_executor(b, None, phase=ultimo.phase)
            or ""
        )
        effort_atual = (assignment_atual.effort if assignment_atual else None) or ""
        decisao = decidir(
            diagnostico,
            tentativa_fase,
            executor_atual=executor_atual,
            effort_atual=effort_atual,
            catalogo=self._catalog,
            max_escalonamentos=self._max_escalonamentos,
        )
        if decisao.acao == ACAO_AUMENTAR_EFFORT and decisao.effort:
            b.orchestration.agent_assignments[ultimo.phase.value] = AgentAssignment(
                executor=executor_atual, effort=decisao.effort
            )
        elif decisao.acao == ACAO_TROCAR_EXECUTOR and decisao.executor:
            b.orchestration.agent_assignments[ultimo.phase.value] = AgentAssignment(
                executor=decisao.executor, effort=effort_atual or None
            )
        b.event_log.append(
            "FailureRouted",
            {
                "orchestration_id": b.orchestration.id,
                "etapa": ETAPA_GATE,
                "fase": ultimo.phase.value,
                "diagnostico": diagnostico,
                "acao": decisao.acao,
                "check": primeiro_check,
                "categoria": categoria,
            },
        )
        nudge = decisao.nudge or (f"O gate reprovou: {detalhe}"[:500] if detalhe else "")
        for card in pendentes:
            record = FailureRecord(
                etapa=ETAPA_GATE,
                tentativa=len(card.failures) + 1,
                comando="quality-gate",
                mensagem=f"Quality gate de {ultimo.phase.value} reprovado",
                saida=detalhe,
                check=primeiro_check,
                categoria=categoria,
            )
            card.failures = registrar(card.failures, record)
            if nudge:
                card.correction_actions = [nudge]
        return [c.id for c in pendentes]

    def snapshot_diff(self, orchestration_id: str, from_v: str, to_v: str) -> dict[str, object]:
        b = self._bundle(orchestration_id)
        sa = b.snapshot_engine.get(from_v)
        sb = b.snapshot_engine.get(to_v)
        if sa is None or sb is None:
            raise KeyError(f"Snapshot inexistente: {from_v if sa is None else to_v}")
        fa, fb = set(sa.frozen_sections), set(sb.frozen_sections)
        keys = set(sa.payload) | set(sb.payload)
        changed = [k for k in keys if sa.payload.get(k) != sb.payload.get(k)]
        # Diff semântico por seção: quais chaves foram adicionadas/removidas/alteradas.
        details = {
            section: _section_delta(sa.payload.get(section), sb.payload.get(section))
            for section in changed
        }
        return {
            "from": from_v,
            "to": to_v,
            "frozen_added": sorted(fb - fa),
            "frozen_removed": sorted(fa - fb),
            "changed_sections": sorted(changed),
            "section_details": details,
        }

    def preview_restore_section(
        self, orchestration_id: str, snapshot_version: str, section: str
    ) -> dict[str, object]:
        """Dry-run da restauração seletiva: mostra o que mudaria, sem aplicar (§23).

        Compara a seção atual do contexto com a do snapshot e devolve o delta semântico,
        para revisão humana antes de confirmar a ação crítica. Somente leitura.
        """
        b = self._bundle(orchestration_id)
        snap = b.snapshot_engine.get(snapshot_version)
        if snap is None:
            raise KeyError(f"Snapshot inexistente: {snapshot_version}")
        if section not in snap.payload:
            raise KeyError(f"Seção inexistente no snapshot: {section}")
        current = b.store.get_path(section)
        target = snap.payload[section]
        delta = _section_delta(current, target)
        return {
            "section": section,
            "from_snapshot": snapshot_version,
            "changes": delta,
            "no_op": not (delta["added"] or delta["removed"] or delta["modified"]),
        }

    def restore_section(
        self, orchestration_id: str, snapshot_version: str, section: str
    ) -> dict[str, object]:
        """Restauração seletiva de UMA seção a partir de um snapshot (§23, ação crítica).

        Espelha o protocolo de rollback (bypass do bus + ADR de rastreabilidade), mas
        restringe o efeito a uma única seção. Endpoint exige papel admin.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            snap = b.snapshot_engine.get(snapshot_version)
            if snap is None:
                raise KeyError(f"Snapshot inexistente: {snapshot_version}")
            if section not in snap.payload:
                raise KeyError(f"Seção inexistente no snapshot: {section}")
            version = b.store.restore_section(section, snap.payload[section])
            b.adr_registry.create(
                title=f"Restauração seletiva: {section} ← {snapshot_version}",
                decision=f"Seção '{section}' restaurada a partir do snapshot {snapshot_version}.",
                phase=b.orchestration.current_phase,
                context="Restauração seletiva de seção (protocolo de contexto §23).",
            )
            b.event_log.append(
                "SectionRestored",
                {"section": section, "from_snapshot": snapshot_version, "version": version},
            )
            self._persist(b)
            return {
                "section": section,
                "from_snapshot": snapshot_version,
                "context_version": version,
            }

    # ------------------------------------------------- cards: mover/atribuir (§28.2)
    def move_card(self, orchestration_id: str, card_id: str, to_column: str) -> KanbanCard:
        b = self._bundle(orchestration_id)
        card = b.board_service.move_card(card_id, ColumnKey(to_column))
        self._persist(b)
        return card

    def block_card(self, orchestration_id: str, card_id: str, reason: str) -> KanbanCard:
        b = self._bundle(orchestration_id)
        card = b.board_service.move_card(card_id, ColumnKey.BLOCKED, reason=reason)
        self._persist(b)
        return card

    def unblock_card(self, orchestration_id: str, card_id: str) -> KanbanCard:
        b = self._bundle(orchestration_id)
        card = b.board_service.move_card(card_id, ColumnKey.READY)
        self._persist(b)
        return card

    def cancel_card(self, orchestration_id: str, card_id: str, reason: str = "") -> KanbanCard:
        """Cancela um card individualmente (§8 do fluxo.md) — distinto de `cancel`,
        que é o kill-switch da orquestração inteira."""
        b = self._bundle(orchestration_id)
        card = b.board_service.move_card(card_id, ColumnKey.CANCELLED, reason=reason)
        self._persist(b)
        return card

    @staticmethod
    def _pending_dependencies(b: OrchestrationBundle, card: KanbanCard) -> list[KanbanCard]:
        """Dependências (§10 do fluxo.md) que ainda não chegaram a `Done`.

        Só usado no caminho manual de execução (`run_card`): o `run_plan` já ordena
        agentes por `depends_on` nas suas próprias ondas e não precisa deste guard.
        """
        pendentes = []
        for dep_id in card.dependencies:
            dep = b.board_service.get_card(dep_id)
            if dep is not None and dep.status != ColumnKey.DONE:
                pendentes.append(dep)
        return pendentes

    def assign_agent(self, orchestration_id: str, card_id: str, agent: str) -> KanbanCard:
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        card.assignee = agent
        card.assignee_type = AssigneeType.AGENT
        b.event_log.append("CardAssigned", {"card_id": card_id, "agent": agent})
        self._persist(b)
        return card

    # ------------------------------------------------------- consultas (leitura)
    def cards_by_status(self, orchestration_id: str, status: str) -> list[str]:
        self._bundle(orchestration_id)
        return self._repo.cards_by_status(orchestration_id, status)

    def count_cards_by_status(self, orchestration_id: str) -> dict[str, int]:
        self._bundle(orchestration_id)
        return self._repo.count_cards_by_status(orchestration_id)

    def adrs_by_status(self, orchestration_id: str, status: str) -> list[str]:
        self._bundle(orchestration_id)
        return self._repo.adrs_by_status(orchestration_id, status)

    def cards_linked_to_adr(self, orchestration_id: str, adr_id: str) -> list[str]:
        self._bundle(orchestration_id)
        return self._repo.cards_linked_to_adr(orchestration_id, adr_id)

    def filter_cards(
        self,
        orchestration_id: str,
        *,
        status: str | None = None,
        card_type: str | None = None,
        assignee: str | None = None,
    ) -> list[KanbanCard]:
        cards = self.get_cards(orchestration_id)
        if status:
            cards = [c for c in cards if c.status.value == status]
        if card_type:
            cards = [c for c in cards if c.type.value == card_type]
        if assignee:
            cards = [c for c in cards if c.assignee == assignee]
        return cards

    def search_adrs(
        self, orchestration_id: str, *, status: str | None = None, query: str | None = None
    ) -> list[ADR]:
        adrs = self.list_adrs(orchestration_id)
        if status:
            adrs = [a for a in adrs if a.status.value == status]
        if query:
            q = query.lower()
            adrs = [a for a in adrs if q in a.title.lower() or q in a.decision.lower()]
        return adrs

    def timeline_page(
        self,
        orchestration_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
        newest_first: bool = False,
    ) -> dict[str, object]:
        """Página da timeline. `newest_first` serve a quem quer "o que acabou de acontecer"."""
        self._bundle(orchestration_id)  # valida existência (404 se não existir)
        page = max(page, 1)
        items, total = self._repo.events_page(
            orchestration_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            newest_first=newest_first,
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "newest_first": newest_first,
        }

    # ------------------------------------------------------------------ execução
    def resolve_provider(
        self,
        executor: str | None,
        *,
        target_path: str | None = None,
        effort: str | None = None,
    ) -> ExecutionProvider | None:
        """Resolve o provider de um executor escolhido (catálogo); None → default.

        `target_path` é a pasta da orquestração (workspace): repassada ao catálogo
        como `repo_override`, faz os agentes CLI operarem nela em vez do repo global.
        """
        if not executor or self._catalog is None:
            return None
        return self._catalog.build(
            executor,
            repo_override=target_path,
            effort_override=effort,
            log_bus=self._log_bus,
        )

    @staticmethod
    def _assignment(b: OrchestrationBundle, key: str | None) -> AgentAssignment | None:
        """Executor configurado para uma etapa (ou para `naming`), se houver."""
        if not key:
            return None
        return b.orchestration.agent_assignments.get(key)

    def _effective_executor(
        self, b: OrchestrationBundle, executor: str | None, *, phase: Phase | None = None
    ) -> str | None:
        """Executor a usar, na ordem: chamada explícita → etapa → padrão → default."""
        if executor:
            return executor
        escolha = self._assignment(b, phase.value if phase else None)
        if escolha is not None:
            return escolha.executor
        if b.orchestration.selected_executor:
            return b.orchestration.selected_executor
        if b.orchestration.target_path and self._catalog is not None:
            return self._catalog.default_name()
        return None

    def _effective_effort(
        self,
        b: OrchestrationBundle,
        executor: str | None,
        effort: str | None,
        *,
        phase: Phase | None = None,
    ) -> str | None:
        """Ordem de resolução (§9 do fluxo.md, ADR-0022): explícito → etapa →
        padrão da orquestração → sugestão automática da ficha → default do perfil.
        A sugestão só preenche o vazio que, sem ela, cairia direto no perfil — toda
        escolha humana (explícita, de etapa ou da orquestração) continua vencendo."""
        if effort:
            return effort
        escolha = self._assignment(b, phase.value if phase else None)
        if escolha is not None:
            # Etapa com executor próprio não herda o esforço global: esforço casa com o
            # modelo, não com a orquestração (um "high" do Codex pode nem existir no
            # modelo escolhido para esta fase). Sem esforço na etapa, usa o do perfil.
            if escolha.effort:
                return escolha.effort
        elif b.orchestration.selected_effort:
            return b.orchestration.selected_effort
        sugerido = self._effort_sugerido(b, executor, phase=phase)
        if sugerido:
            return sugerido
        if executor and self._catalog is not None:
            profile = self._catalog.get(executor)
            return profile.effort if profile is not None else None
        return None

    def _effort_sugerido(
        self, b: OrchestrationBundle, executor: str | None, *, phase: Phase | None = None
    ) -> str | None:
        """§9: complexidade + risco da ficha da demanda sugerem o esforço.

        Só age quando a triagem de fato rodou (`demand_brief` não vazio) — ficha
        vazia é o mesmo "nunca triou" das demais orquestrações, e não pode mudar o
        comportamento de nenhuma delas. `ASO_EFFORT_AUTOMATICO=0` desliga por
        completo (interruptor de emergência).
        """
        if not self._effort_automatico or not b.orchestration.demand_brief:
            return None
        brief = DemandBrief.model_validate(b.orchestration.demand_brief)
        sugestao = sugerir_effort(brief.complexidade, brief.risco)
        suportados: list[str] = []
        if executor and self._catalog is not None:
            perfil = self._catalog.get(executor)
            if perfil is not None:
                suportados = list(perfil.supported_efforts)
        resolvido = resolver_topo(sugestao, suportados)
        b.event_log.append(
            "EffortSugerido",
            {
                "orchestration_id": b.orchestration.id,
                "fase": phase.value if phase else None,
                "complexidade": brief.complexidade,
                "risco": brief.risco.value,
                "effort": resolvido,
            },
        )
        return resolvido

    def _provider_for(
        self,
        b: OrchestrationBundle,
        executor: str | None,
        effort: str | None = None,
        *,
        phase: Phase | None = None,
    ) -> ExecutionProvider | None:
        """Provider a usar nesta etapa, atrelado à pasta da orquestração (se houver).

        - executor escolhido (chamada ou etapa) → resolve do catálogo com a pasta;
        - sem executor, mas com pasta definida → usa o executor default do catálogo,
          também atrelado à pasta (evita cair no provider global, que aponta para
          o `ASO_TARGET_REPO`);
        - senão → provider global do bootstrap (comportamento legado).
        """
        tp = b.orchestration.target_path
        effective_executor = self._effective_executor(b, executor, phase=phase)
        effective_effort = self._effective_effort(b, effective_executor, effort, phase=phase)
        if effective_executor and self._catalog is not None:
            try:
                self._validate_executor(effective_executor, effective_effort)
            except ValueError as exc:
                b.event_log.append(
                    "ExecutorRejected",
                    {
                        "orchestration_id": b.orchestration.id,
                        "executor": effective_executor,
                        "reason": str(exc),
                    },
                )
                self._persist(b)
                raise
            return self.resolve_provider(
                effective_executor, target_path=tp, effort=effective_effort
            )
        return self._provider

    def _workspace_for(self, b: OrchestrationBundle) -> WorktreeManager:
        """Resolve o worktree da própria orquestração, nunca o provider global."""
        if b.orchestration.target_path:
            return WorktreeManager(b.orchestration.target_path)
        legacy = getattr(self._provider, "worktree", None)
        if isinstance(legacy, WorktreeManager):
            return legacy
        raise ValueError("Orquestração sem pasta de trabalho para operação git.")

    # -------------------------------------- worktrees órfãos (§1.4/§3.3, ADR-0027)
    _STATUS_INATIVOS = (ColumnKey.DONE, ColumnKey.CANCELLED, ColumnKey.ARCHIVED)

    def _branches_ativas(self, b: OrchestrationBundle) -> set[str]:
        """Branches que ainda importam: cards não terminais referenciam por
        `branch`/`worktree` — um worktree fora daqui é candidato a órfão."""
        ativos: set[str] = set()
        for card in b.board_service.cards_of(b.board.id):
            if card.status in self._STATUS_INATIVOS:
                continue
            if card.branch:
                ativos.add(card.branch)
            if card.worktree:
                ativos.add(card.worktree)
        return ativos

    def list_worktrees(self, orchestration_id: str) -> list[dict[str, Any]]:
        """O que existe em disco para esta orquestração, com `orfao` marcado — sempre
        a lista completa (com o que **seria** removido), nunca só os órfãos: o
        operador precisa ver o que está ativo para confiar no que não está."""
        b = self._bundle(orchestration_id)
        ativos = self._branches_ativas(b)
        encontrados = self._workspace_for(b).list_worktrees()
        return [{**w, "orfao": w.get("branch", "") not in ativos} for w in encontrados]

    def prune_worktrees(
        self, orchestration_id: str, *, actor: str = "system"
    ) -> list[dict[str, Any]]:
        """Remove só os órfãos (`git worktree remove` + `prune`, nunca `rm -rf`) e
        devolve o que foi removido — o banco não é tocado."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            ativos = self._branches_ativas(b)
            workspace = self._workspace_for(b)
            todos = workspace.list_worktrees()
            orfaos = [w for w in todos if w.get("branch", "") not in ativos]
            workspace.prune([Path(w["path"]) for w in orfaos if w.get("path")])
            b.event_log.append(
                "WorktreesPruned",
                {"orchestration_id": orchestration_id, "actor": actor, "removidos": orfaos},
            )
            self._persist(b)
            return orfaos

    def agent_log(
        self, orchestration_id: str, *, after: int = 0, limit: int = 500
    ) -> dict[str, Any]:
        """Saída ao vivo dos agentes desta orquestração (ADR-0015).

        `after` é o cursor: a tela pede só as linhas que ainda não viu, o que permite
        acompanhar a execução em andamento e também reexibir o log ao recarregar a página.
        """
        self._bundle(orchestration_id)  # 404 coerente com o resto da API
        linhas = self._log_bus.lines(orchestration_id, after=after, limit=limit)
        estado = self._log_bus.state(orchestration_id)
        return {
            "lines": [linha.public() for linha in linhas],
            "next": linhas[-1].seq if linhas else after,
            **estado,
        }

    def list_executors(self) -> list[dict[str, object]]:
        """Executores disponíveis (para escolha por etapa na UI/API)."""
        return self._catalog.entries() if self._catalog is not None else []

    def _validate_executor(self, name: str, effort: str | None = None) -> ExecutorProfile:
        if self._catalog is None:
            raise ValueError("Catálogo de executores não configurado.")
        profile = self._catalog.validate(name, effort)
        if profile.managed_by != "codex":
            return profile
        with self._codex_lock:
            capabilities = self._codex_cache.get("capabilities")
            if capabilities is None:
                try:
                    capabilities = discover_codex()
                except CodexDiscoveryError as exc:
                    raise ValueError(f"Não foi possível validar o executor Codex: {exc}") from exc
                self._codex_cache.set("capabilities", capabilities)
        models = {model.model: model for model in capabilities.models}
        model = (
            models.get(profile.model)
            if profile.model
            else next(
                (candidate for candidate in capabilities.models if candidate.is_default),
                capabilities.models[0],
            )
        )
        if profile.model and model is None:
            raise ValueError(
                f"Executor '{name}' indisponível: modelo não anunciado pelo Codex atual."
            )
        if model is not None and (effort or profile.effort) not in model.supported_efforts:
            raise ValueError(
                f"Esforço '{effort or profile.effort}' não é aceito por {model.model}; "
                f"use: {', '.join(model.supported_efforts)}."
            )
        return profile

    def sync_codex_executors(self) -> list[dict[str, object]]:
        """Descobre o Codex efetivo e substitui somente os perfis gerenciados."""
        if self._catalog is None:
            self._catalog = ExecutorCatalog()
        with self._codex_lock:
            try:
                capabilities = discover_codex()
            except CodexDiscoveryError:
                raise
            self._catalog.replace_managed_codex(managed_codex_profiles(capabilities))
            self._codex_cache.set("capabilities", capabilities)
            if self._executor_store is not None:
                self._executor_store.save(self._catalog.profiles())
        return self._catalog.entries()

    def update_execution_settings(
        self,
        orchestration_id: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
        validation_command: str | None = None,
        actor: str = "system",
    ) -> Orchestration:
        """Atualiza uma execução ainda não iniciada, com evento auditável."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if b.orchestration.status not in {"created", "blocked"}:
                raise ValueError(
                    "Configurações só podem mudar em orquestrações criadas ou bloqueadas."
                )
            next_executor = executor or b.orchestration.selected_executor
            next_effort = effort or b.orchestration.selected_effort
            if next_executor is not None and self._catalog is not None:
                self._validate_executor(next_executor, next_effort)
            before = {
                "executor": b.orchestration.selected_executor,
                "effort": b.orchestration.selected_effort,
                "validation_command": b.orchestration.validation_command,
            }
            if executor is not None:
                b.orchestration.selected_executor = executor
            if effort is not None:
                b.orchestration.selected_effort = effort
            if validation_command is not None:
                b.orchestration.validation_command = validate_gate_command(validation_command)
            b.orchestration.updated_at = now_iso()
            after = {
                "executor": b.orchestration.selected_executor,
                "effort": b.orchestration.selected_effort,
                "validation_command": b.orchestration.validation_command,
            }
            b.event_log.append(
                "ExecutionSettingsUpdated",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "before": before,
                    "after": after,
                },
            )
            self._persist(b)
            return b.orchestration

    def get_validation_checks(self, orchestration_id: str) -> list[ValidationCheck]:
        """A bateria efetiva (§12, ADR-0022) — bateria configurada, ou o
        `validation_command` legado convertido numa única verificação "testes"."""
        b = self._bundle(orchestration_id)
        return checks_efetivos(b.orchestration)

    def set_validation_checks(
        self, orchestration_id: str, checks: list[ValidationCheck], *, actor: str = "system"
    ) -> Orchestration:
        """Substitui a bateria de validações (§12). Ação de operador (`PUT`) —
        cada comando passa por `validate_gate_command`, exatamente como o
        `validation_command` legado: um `npm run dev` no meio da lista travaria o
        gate para sempre, tanto quanto travaria sozinho."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            validados = [
                check.model_copy(update={"comando": validate_gate_command(check.comando)})
                for check in checks
            ]
            antes = [c.model_dump(mode="json") for c in b.orchestration.validation_checks]
            b.orchestration.validation_checks = validados
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "ValidationChecksUpdated",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "before": antes,
                    "after": [c.model_dump(mode="json") for c in validados],
                },
            )
            self._persist(b)
            return b.orchestration

    def suggest_validation_checks(self, orchestration_id: str) -> list[ValidationCheck]:
        """Sugestão determinística por stack (§4.5) — não grava nada. Sem
        `target_path`, não há workspace para inspecionar: lista vazia, não erro."""
        b = self._bundle(orchestration_id)
        if not b.orchestration.target_path:
            return []
        return sugerir_bateria(b.orchestration.target_path)

    # -------------------------------------------- orçamento com freio (§1.2/§3.2)
    def set_orcamento(
        self, orchestration_id: str, teto_usd: float | None, *, actor: str = "system"
    ) -> Orchestration:
        """Eleva (ou remove) o teto de gasto (ADR-0026). `None`/`<= 0` volta ao
        comportamento sem teto. Ação crítica (`admin`, ver `api/auth.py`): autorizar
        mais gasto é decisão humana, mesmo espírito da regra 4 do CLAUDE.md."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            antes = b.orchestration.orcamento_usd
            b.orchestration.orcamento_usd = teto_usd if teto_usd and teto_usd > 0 else None
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "OrcamentoAtualizado",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "antes": antes,
                    "depois": b.orchestration.orcamento_usd,
                },
            )
            self._persist(b)
            return b.orchestration

    # ------------------------------------------ implantação governada (§18-22)
    def set_deploy_config(
        self,
        orchestration_id: str,
        *,
        command: str | None = None,
        environment: str | None = None,
        health_checks: list[ValidationCheck] | None = None,
        rollback_command: str | None = None,
        actor: str = "system",
    ) -> Orchestration:
        """Configura a implantação (ADR-0023) — cada comando passa por
        `validate_gate_command`, mesmo guard de `set_validation_checks`."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            antes = {
                "deploy_command": b.orchestration.deploy_command,
                "deploy_environment": b.orchestration.deploy_environment,
                "deploy_health_checks": [
                    c.model_dump(mode="json") for c in b.orchestration.deploy_health_checks
                ],
                "deploy_rollback_command": b.orchestration.deploy_rollback_command,
            }
            if command is not None:
                b.orchestration.deploy_command = validate_gate_command(command) if command else None
            if environment is not None:
                b.orchestration.deploy_environment = environment
            if health_checks is not None:
                b.orchestration.deploy_health_checks = [
                    c.model_copy(update={"comando": validate_gate_command(c.comando)})
                    for c in health_checks
                ]
            if rollback_command is not None:
                b.orchestration.deploy_rollback_command = (
                    validate_gate_command(rollback_command) if rollback_command else None
                )
            depois = {
                "deploy_command": b.orchestration.deploy_command,
                "deploy_environment": b.orchestration.deploy_environment,
                "deploy_health_checks": [
                    c.model_dump(mode="json") for c in b.orchestration.deploy_health_checks
                ],
                "deploy_rollback_command": b.orchestration.deploy_rollback_command,
            }
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DeployConfigUpdated",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "before": antes,
                    "after": depois,
                },
            )
            self._persist(b)
            return b.orchestration

    def run_deploy(
        self,
        orchestration_id: str,
        *,
        environment: str | None = None,
        versao_app: str = "",
        commit: str = "",
        branch: str = "",
        actor: str = "system",
    ) -> DeployRun:
        """§18 (checklist) + §19 (execução). Sempre roda o comando configurado —
        a decisão humana (§18/§22) é sobre ACEITAR o resultado, não sobre
        autorizar a tentativa (mesmo raciocínio de `DiscoveryService.investigar`).
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.deploy_command:
                raise ValueError(
                    "Configure o comando de implantação antes (PUT .../deploy/config)."
                )
            repo = b.orchestration.target_path or os.environ.get("ASO_TARGET_REPO")
            if not repo:
                raise ValueError("Orquestração sem pasta de trabalho (target_path).")
            if not b.gate_results or b.gate_results[-1].status != GateStatus.PASSED:
                raise ValueError(
                    "Quality gate mais recente não passou — rode-o antes de implantar (§18)."
                )
            ok, logs, duracao = executar_deploy(b.orchestration.deploy_command, repo)
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            deploy = DeployRun(
                ambiente=environment or b.orchestration.deploy_environment,
                versao_app=versao_app,
                commit=commit,
                branch=branch,
                comando=b.orchestration.deploy_command,
                responsavel=actor,
                status=STATUS_SUCESSO if ok else STATUS_FALHOU,
                logs=logs[:4000],
                resultado=logs[:500],
                duracao_segundos=duracao,
            )
            if not ok:
                deploy.aceite_status = ACEITE_REPROVADO
                deploy.aceite_comentario = "implantação falhou"
            elif exige_aceite_humano(deploy, brief):
                deploy.aceite_status = ACEITE_AGUARDANDO_HUMANO
            else:
                deploy.aceite_status = ACEITE_APROVADO
                deploy.origem_decisao = "automatico"
            deploy.versao = proxima_versao(b.orchestration.deploy_runs)
            b.orchestration.deploy_runs = acrescentar_versao(b.orchestration.deploy_runs, deploy)
            b.event_log.append(
                "DeployRun",
                {
                    "orchestration_id": orchestration_id,
                    "status": deploy.status,
                    "ambiente": deploy.ambiente,
                    "aceite": deploy.aceite_status,
                },
            )
            self._persist(b)
            return deploy

    def get_deploy(self, orchestration_id: str) -> DeployRun:
        b = self._bundle(orchestration_id)
        return versao_atual(b.orchestration.deploy_runs, DeployRun)

    def get_deploy_history(self, orchestration_id: str) -> list[DeployRun]:
        b = self._bundle(orchestration_id)
        return [DeployRun.model_validate(d) for d in b.orchestration.deploy_runs]

    def validate_deploy(self, orchestration_id: str, *, actor: str = "system") -> DeployRun:
        """§20: roda as verificações pós-implantação sobre a última tentativa."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.deploy_runs:
                raise KeyError("Nenhuma implantação para validar.")
            repo = b.orchestration.target_path or os.environ.get("ASO_TARGET_REPO")
            if not repo:
                raise ValueError("Orquestração sem pasta de trabalho (target_path).")
            deploy = versao_atual(b.orchestration.deploy_runs, DeployRun)
            aprovado, resultados = validar_pos_deploy(b.orchestration.deploy_health_checks, repo)
            deploy.validacao_status = VALIDACAO_APROVADA if aprovado else VALIDACAO_REPROVADA
            deploy.validacao_resultados = resultados
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            # Uma validação reprovada pode reverter um aceite já automático — a
            # decisão humana reabre exatamente como no §22.
            if deploy.aceite_status == ACEITE_APROVADO and exige_aceite_humano(deploy, brief):
                deploy.aceite_status = ACEITE_AGUARDANDO_HUMANO
                deploy.origem_decisao = ""
            b.orchestration.deploy_runs = [
                *b.orchestration.deploy_runs[:-1],
                deploy.model_dump(mode="json"),
            ]
            b.event_log.append(
                "DeployValidated",
                {"orchestration_id": orchestration_id, "aprovado": aprovado, "actor": actor},
            )
            self._persist(b)
            return deploy

    def decide_deploy(
        self, orchestration_id: str, *, approved: bool, comentario: str = "", actor: str = "system"
    ) -> DeployRun:
        """§22: aceite final humano, só quando o ciclo automático escalou."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.deploy_runs:
                raise KeyError("Nenhuma implantação para decidir.")
            deploy = versao_atual(b.orchestration.deploy_runs, DeployRun)
            if deploy.aceite_status != ACEITE_AGUARDANDO_HUMANO:
                raise ValueError(
                    f"Implantação não está aguardando aceite (status={deploy.aceite_status})."
                )
            deploy.aceite_status = ACEITE_APROVADO if approved else ACEITE_REPROVADO
            deploy.aceite_comentario = comentario
            deploy.origem_decisao = "humano"
            b.orchestration.deploy_runs = [
                *b.orchestration.deploy_runs[:-1],
                deploy.model_dump(mode="json"),
            ]
            b.event_log.append(
                "DeployDecided",
                {"orchestration_id": orchestration_id, "approved": approved, "actor": actor},
            )
            self._persist(b)
            return deploy

    def rollback_deploy(
        self, orchestration_id: str, *, reason: str, actor: str = "system"
    ) -> DeployRun:
        """§21: reverte a última implantação e abre uma tarefa de análise de
        causa raiz (CardType.INCIDENT) — o runtime não reverte infraestrutura
        real; roda `deploy_rollback_command` quando configurado (best-effort)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.deploy_runs:
                raise KeyError("Nenhuma implantação para reverter.")
            deploy = versao_atual(b.orchestration.deploy_runs, DeployRun)
            if deploy.status == STATUS_REVERTIDO:
                raise ValueError("Implantação já revertida.")
            detalhe = ""
            comando_rollback = b.orchestration.deploy_rollback_command
            repo = b.orchestration.target_path or os.environ.get("ASO_TARGET_REPO")
            if comando_rollback and repo:
                _ok, detalhe, _duracao = executar_deploy(comando_rollback, repo)
            deploy.status = STATUS_REVERTIDO
            deploy.rollback_motivo = reason
            b.orchestration.deploy_runs = [
                *b.orchestration.deploy_runs[:-1],
                deploy.model_dump(mode="json"),
            ]
            descricao = reason
            if detalhe:
                descricao += f"\n\nSaída do comando de rollback: {detalhe[:1000]}"
            card = KanbanCard(
                board_id=b.board.id,
                orchestration_id=orchestration_id,
                phase=b.orchestration.current_phase,
                type=CardType.INCIDENT,
                title=f"Causa raiz: rollback de implantação ({deploy.ambiente})",
                description=descricao,
                status=ColumnKey.BACKLOG,
                linked_requirements=["§21"],
            )
            b.board_service.add_card(card)
            b.event_log.append(
                "DeployRolledBack",
                {
                    "orchestration_id": orchestration_id,
                    "ambiente": deploy.ambiente,
                    "reason": reason,
                    "incident_card": card.id,
                    "actor": actor,
                },
            )
            self._persist(b)
            return deploy

    @staticmethod
    def _validate_assignment_key(orchestration: Orchestration, key: str) -> str:
        """Valida a chave da etapa e o momento em que ela ainda pode ser configurada.

        `naming`, `triagem`, `revisao`, `discovery` e `especificacao` são sempre
        editáveis (não são fases da esteira). Uma fase só aceita troca de agente
        enquanto não ficou para trás: reconfigurar F2 com a orquestração já em F5
        daria a falsa impressão de que o trabalho seria refeito com o novo agente.
        """
        if key in (NAMING_KEY, TRIAGE_KEY, REVIEW_KEY, DISCOVERY_KEY, SPEC_KEY):
            return key
        try:
            fase = Phase(key)
        except ValueError:
            raise ValueError(
                f"Etapa inválida: '{key}'. Use F1..F7, '{NAMING_KEY}', '{TRIAGE_KEY}', "
                f"'{REVIEW_KEY}', '{DISCOVERY_KEY}' ou '{SPEC_KEY}'."
            ) from None
        ordem = list(Phase)
        if ordem.index(fase) < ordem.index(orchestration.current_phase):
            raise ValueError(
                f"A fase {fase.value} já passou (esteira em "
                f"{orchestration.current_phase.value}): a escolha não teria efeito."
            )
        return fase.value

    def set_agent_assignment(
        self,
        orchestration_id: str,
        key: str,
        *,
        executor: str,
        effort: str | None = None,
        actor: str = "system",
    ) -> Orchestration:
        """Define o executor de uma etapa (F1..F7) ou do nomeador. Ação auditável."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if b.orchestration.status == "cancelled":
                raise ValueError("Orquestração cancelada: configuração bloqueada.")
            chave = self._validate_assignment_key(b.orchestration, key)
            if self._catalog is not None:
                self._validate_executor(executor, effort)
            antes = b.orchestration.agent_assignments.get(chave)
            b.orchestration.agent_assignments[chave] = AgentAssignment(
                executor=executor, effort=effort
            )
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "AgentAssignmentUpdated",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "key": chave,
                    "before": antes.model_dump() if antes else None,
                    "after": {"executor": executor, "effort": effort},
                },
            )
            self._persist(b)
            return b.orchestration

    def clear_agent_assignment(
        self, orchestration_id: str, key: str, *, actor: str = "system"
    ) -> Orchestration:
        """Remove o executor da etapa: ela volta a herdar o padrão da orquestração."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            chave = self._validate_assignment_key(b.orchestration, key)
            antes = b.orchestration.agent_assignments.pop(chave, None)
            if antes is None:
                return b.orchestration  # já era o padrão: nada a auditar
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "AgentAssignmentUpdated",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "key": chave,
                    "before": antes.model_dump(),
                    "after": None,
                },
            )
            self._persist(b)
            return b.orchestration

    # -------------------------------------------------------------- ficha da demanda
    def _triage_executor(
        self, explicit: str | None, assignment: AgentAssignment | None
    ) -> str | None:
        """Ordem de resolução do agente de triagem: parâmetro explícito → etapa
        'triagem' configurada → default do catálogo → heurística (`None`)."""
        if explicit:
            return explicit
        if assignment is not None:
            return assignment.executor
        if self._catalog is not None:
            return self._catalog.default_name()
        return None

    def triage_demand(
        self, user_request: str, *, executor: str | None = None, effort: str | None = None
    ) -> DemandBrief:
        """Tria a demanda (§1/§2) antes de criar a orquestração.

        Ainda não existe orquestração, logo não há `agent_assignments["triagem"]`: o
        agente vem do parâmetro explícito ou do default do catálogo, e cai na
        heurística sem nenhum dos dois — a mesma garantia de `TriageService`, triar
        nunca impede a criação.
        """
        nome = self._triage_executor(executor, None)
        assignment = AgentAssignment(executor=nome, effort=effort) if nome else None
        return self._triage.analisar(assignment, user_request=user_request)

    def create_with_triage(
        self,
        user_request: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
        **kwargs: Any,
    ) -> Orchestration:
        """Tria a demanda e cria a orquestração — o único caminho correto de criação.

        Existe porque a sequência triagem→criação estava duplicada só em `app.py`: a
        CLI nasceu sem ela ([Ponto 1] herdado da avaliação do Incremento A) e criava
        orquestrações com `demand_brief` vazio e `priority` sempre `MEDIUM` fixo — o
        motor de decisão nunca via a demanda real. `create_orchestration` continua
        existindo tal como está (usada em dezenas de testes); este método a envolve.
        """
        brief = self.triage_demand(user_request, executor=executor, effort=effort)
        return self.create_orchestration(
            user_request,
            executor=executor,
            effort=effort,
            decision_input=brief.to_decision_input(user_request),
            demand_brief=brief,
            **kwargs,
        )

    def get_demand_brief(self, orchestration_id: str) -> DemandBrief:
        """Ficha atual da demanda (vazia = orquestração criada antes da ADR-0016)."""
        b = self._bundle(orchestration_id)
        return DemandBrief.model_validate(b.orchestration.demand_brief)

    def set_demand_brief(
        self, orchestration_id: str, brief: DemandBrief, *, actor: str = "system"
    ) -> Orchestration:
        """Persiste a ficha da demanda, com trilha de auditoria (origem/fallback)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            b.orchestration.demand_brief = brief.model_dump(mode="json")
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DemandTriaged",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "origem": brief.origem,
                    "fallback_reason": brief.fallback_reason,
                },
            )
            self._persist(b)
            return b.orchestration

    def retriage_demand(
        self,
        orchestration_id: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
        actor: str = "system",
    ) -> dict[str, object]:
        """Re-tria a demanda (POST .../brief), depois que o operador responder as
        `perguntas_abertas`. O agente roda fora do lock — mesmo motivo de `run_card`:
        não travar a orquestração pelo timeout da triagem; só a persistência do
        resultado é serializada.

        [Ponto 2 herdado da avaliação do Incremento A] Antes, só a ficha era
        atualizada: o operador respondia as `perguntas_abertas`, ganhava uma ficha
        melhor e continuava com a mesma equipe/estratégia da triagem original — o
        mecanismo que o Incremento A existe para ligar ficava desligado no caminho de
        correção. Ver `_replan_if_untouched`.
        """
        b = self._bundle(orchestration_id)
        assignment = self._assignment(b, TRIAGE_KEY)
        nome = self._triage_executor(executor, assignment)
        efetivo_effort = effort or (assignment.effort if assignment else None)
        escolha = AgentAssignment(executor=nome, effort=efetivo_effort) if nome else None
        brief = self._triage.analisar(escolha, user_request=b.orchestration.user_request)
        self.set_demand_brief(orchestration_id, brief, actor=actor)
        replanned, motivo = self._replan_if_untouched(orchestration_id, brief, actor=actor)
        return {"demand_brief": brief, "replanned": replanned, "replan_reason": motivo}

    def _replan_if_untouched(
        self, orchestration_id: str, brief: DemandBrief, *, actor: str
    ) -> tuple[bool, str]:
        """Recomputa o `ExecutionPlan` a partir da ficha re-triada — só enquanto nenhum
        card saiu de Ready. Depois de executado, replanejar mentiria sobre o trabalho
        já feito (mesma razão de `_validate_assignment_key` recusar reconfigurar uma
        fase que já ficou para trás). Devolve `(replanejou, motivo)`.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            cards = b.board_service.cards_of(b.board.id)
            if any(c.status != ColumnKey.READY for c in cards):
                motivo = (
                    "cards já saíram de Ready: replanejar agora reescreveria trabalho em andamento"
                )
                b.event_log.append(
                    "ReplanSkipped",
                    {"orchestration_id": orchestration_id, "actor": actor, "reason": motivo},
                )
                self._persist(b)
                return False, motivo
            planner = ExecutionPlanner(MultiAgentDecisionEngine())
            din = brief.to_decision_input(b.orchestration.user_request)
            novo_plano = planner.plan(orchestration_id, b.orchestration.execution_mode, din)
            b.plan = novo_plano
            nova_prioridade = prioridade_de(brief)
            for card in cards:
                card.priority = nova_prioridade
            b.event_log.append(
                "Replanned",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "strategy": novo_plano.strategy.value,
                    "cards_repriced": len(cards),
                },
            )
            self._persist(b)
            return True, ""

    # ------------------------------------------------- discovery e aprovação (§3/§4)
    def _discovery_executor(
        self, explicit: str | None, assignment: AgentAssignment | None
    ) -> str | None:
        """Ordem de resolução do agente de discovery: parâmetro explícito → etapa
        'discovery' configurada → default do catálogo → heurística (`None`)."""
        if explicit:
            return explicit
        if assignment is not None:
            return assignment.executor
        if self._catalog is not None:
            return self._catalog.default_name()
        return None

    def run_discovery(
        self, orchestration_id: str, *, executor: str | None = None, effort: str | None = None
    ) -> Orchestration:
        """Roda o discovery (§3) e aplica a regra de aprovação automática/humana (§4).

        Reexecutar depois de uma reprovação acrescenta uma NOVA versão ao ring (§4.2,
        ADR-0021) — o comentário da reprovação anterior entra no pedido ao agente
        (ADR-0020), para ele ajustar o documento e submeter de novo (mesmo mecanismo
        do §4), e sobrevive como histórico consultável, não só no prompt seguinte.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            tp = b.orchestration.target_path
            if not tp:
                raise ValueError("Discovery exige uma pasta de trabalho (target_path) definida.")
            ws = WorkspaceService()
            root = ws.validate(tp)
            workspace_report = WorkspaceAnalyzer(ws).analyze(root)
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            anterior = versao_atual(b.orchestration.discovery_reports, DiscoveryReport)
            comentarios = (
                anterior.revisao_comentarios if anterior.status == STATUS_REPROVADO else ""
            )
            assignment_ref = self._assignment(b, DISCOVERY_KEY)
            nome = self._discovery_executor(executor, assignment_ref)
            efetivo_effort = effort or (assignment_ref.effort if assignment_ref else None)
            assignment = AgentAssignment(executor=nome, effort=efetivo_effort) if nome else None
            report = self._discovery.investigar(
                assignment,
                user_request=b.orchestration.user_request,
                demand_brief=brief,
                workspace_report=workspace_report,
                comentarios_anteriores=comentarios,
            )
            report.status = (
                STATUS_AGUARDANDO_APROVACAO
                if exige_aprovacao_discovery(report, brief)
                else STATUS_APROVADO
            )
            report.versao = proxima_versao(b.orchestration.discovery_reports)
            b.orchestration.discovery_reports = acrescentar_versao(
                b.orchestration.discovery_reports, report
            )
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DiscoveryRun",
                {
                    "orchestration_id": orchestration_id,
                    "status": report.status,
                    "origem": report.origem,
                    "versao": report.versao,
                },
            )
            self._persist(b)
            return b.orchestration

    def get_discovery_report(self, orchestration_id: str) -> DiscoveryReport:
        """Versão corrente do discovery (vazio = discovery ainda não rodado)."""
        b = self._bundle(orchestration_id)
        return versao_atual(b.orchestration.discovery_reports, DiscoveryReport)

    def get_discovery_history(self, orchestration_id: str) -> list[DiscoveryReport]:
        """Histórico de versões do discovery (§4.2, ADR-0021) — ring de até 5."""
        b = self._bundle(orchestration_id)
        return [DiscoveryReport.model_validate(d) for d in b.orchestration.discovery_reports]

    def decide_discovery(
        self,
        orchestration_id: str,
        *,
        approved: bool,
        comentario: str = "",
        actor: str = "system",
    ) -> Orchestration:
        """Decide a aprovação humana do discovery (§4) — ação crítica (regra 4 do
        CLAUDE.md), papel admin checado no handler da API (mesmo padrão de
        `report_review`). Atualiza a versão corrente no lugar — decidir não cria uma
        versão nova, só muda o status da que já existe."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.discovery_reports:
                raise KeyError("Nenhum relatório de discovery para decidir.")
            report = versao_atual(b.orchestration.discovery_reports, DiscoveryReport)
            if report.status != STATUS_AGUARDANDO_APROVACAO:
                raise ValueError(
                    f"Discovery não está aguardando aprovação (status={report.status})."
                )
            report.status = STATUS_APROVADO if approved else STATUS_REPROVADO
            report.revisao_comentarios = comentario
            b.orchestration.discovery_reports = [
                *b.orchestration.discovery_reports[:-1],
                report.model_dump(mode="json"),
            ]
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DiscoveryDecided",
                {"orchestration_id": orchestration_id, "approved": approved, "actor": actor},
            )
            self._persist(b)
            return b.orchestration

    # --------------------------------------------- especificação e revisão documental (§5/§6)
    def _spec_executor(
        self, explicit: str | None, assignment: AgentAssignment | None
    ) -> str | None:
        """Ordem de resolução do agente de especificação: parâmetro explícito → etapa
        'especificacao' configurada → default do catálogo → heurística (`None`)."""
        if explicit:
            return explicit
        if assignment is not None:
            return assignment.executor
        if self._catalog is not None:
            return self._catalog.default_name()
        return None

    def run_spec(
        self, orchestration_id: str, *, executor: str | None = None, effort: str | None = None
    ) -> Orchestration:
        """Gera/regenera a especificação (§5) — exige discovery aprovado (`ValueError`
        propagado por `SpecService.especificar`, viram 409 no handler da API)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            discovery = versao_atual(b.orchestration.discovery_reports, DiscoveryReport)
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            anterior = versao_atual(b.orchestration.spec_documents, SpecDocument)
            comentarios = (
                anterior.revisao_comentarios if anterior.status == SPEC_STATUS_REPROVADO else ""
            )
            assignment_ref = self._assignment(b, SPEC_KEY)
            nome = self._spec_executor(executor, assignment_ref)
            efetivo_effort = effort or (assignment_ref.effort if assignment_ref else None)
            assignment = AgentAssignment(executor=nome, effort=efetivo_effort) if nome else None
            spec = self._spec.especificar(
                assignment,
                demand_brief=brief,
                discovery=discovery,
                comentarios_anteriores=comentarios,
            )
            spec.versao = proxima_versao(b.orchestration.spec_documents)
            # Rodadas do ciclo de revisão (§4.4) atravessam regenerações — zeram só
            # quando não há versão anterior (spec gerada pela primeira vez).
            tem_versao_anterior = bool(b.orchestration.spec_documents)
            spec.rodadas_revisao = anterior.rodadas_revisao if tem_versao_anterior else 0
            b.orchestration.spec_documents = acrescentar_versao(
                b.orchestration.spec_documents, spec
            )
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "SpecRun",
                {
                    "orchestration_id": orchestration_id,
                    "status": spec.status,
                    "origem": spec.origem,
                    "versao": spec.versao,
                },
            )
            self._persist(b)
            return b.orchestration

    def get_spec(self, orchestration_id: str) -> SpecDocument:
        """Versão corrente da especificação (vazio = ainda não gerada)."""
        b = self._bundle(orchestration_id)
        return versao_atual(b.orchestration.spec_documents, SpecDocument)

    def get_spec_history(self, orchestration_id: str) -> list[SpecDocument]:
        """Histórico de versões da especificação (§4.2, ADR-0021) — ring de até 5."""
        b = self._bundle(orchestration_id)
        return [SpecDocument.model_validate(s) for s in b.orchestration.spec_documents]

    def run_spec_review(
        self, orchestration_id: str, *, executor: str | None = None, actor: str = "system"
    ) -> Orchestration:
        """Roda a revisão documental (§6) sobre a versão corrente da especificação.

        O revisor precisa ser diferente de quem produziu o documento (mesmo princípio
        do §14 aplicado a documentos). Esgotado `ASO_MAX_RODADAS_DOC`, uma reprovação
        vira `necessita_humano` em vez de continuar o ciclo indefinidamente.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.spec_documents:
                raise KeyError("Nenhuma especificação para revisar.")
            spec = versao_atual(b.orchestration.spec_documents, SpecDocument)
            if spec.status != SPEC_STATUS_AGUARDANDO_REVISAO:
                raise ValueError(
                    f"Especificação não está aguardando revisão (status={spec.status})."
                )
            origem_executor = spec.origem if spec.origem != "heuristica" else None
            revisor, recusa = self._resolve_reviewer(
                b, origem_executor=origem_executor, explicit=executor
            )
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            # A checagem determinística (§6: plano de testes/rollback) roda mesmo sem
            # revisor disponível — ela não depende de agente. Só cai no fallback
            # genérico de `recusa` quando o documento passa nela.
            assignment = (
                None if recusa else (AgentAssignment(executor=revisor) if revisor else None)
            )
            doc_verdito = self._review.revisar_documento(
                assignment, documento=spec, tipo=SPEC_KEY, brief=brief
            )
            if recusa and doc_verdito.origem != "checagem_deterministica":
                doc_verdito = doc_verdito.model_copy(update={"fallback_reason": recusa})
            spec.rodadas_revisao += 1
            veredito = doc_verdito.veredito
            if veredito == VEREDITO_DOC_REPROVADO and spec.rodadas_revisao >= self._max_rodadas_doc:
                veredito = SPEC_STATUS_NECESSITA_HUMANO
            spec.status = veredito
            spec.revisao_comentarios = doc_verdito.resumo or (
                "; ".join(a.descricao for a in doc_verdito.acoes) if doc_verdito.acoes else ""
            )
            b.orchestration.spec_documents = [
                *b.orchestration.spec_documents[:-1],
                spec.model_dump(mode="json"),
            ]
            b.orchestration.updated_at = now_iso()
            cards_criados = (
                self._materialize_spec_cards(b, spec) if veredito in SPEC_STATUS_APROVADOS else []
            )
            b.event_log.append(
                "SpecReviewed",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "veredito": veredito,
                    "revisor": doc_verdito.revisor,
                    "rodadas": spec.rodadas_revisao,
                    "cards_criados": len(cards_criados),
                },
            )
            self._persist(b)
            return b.orchestration

    def approve_spec(
        self,
        orchestration_id: str,
        *,
        approved: bool,
        comentario: str = "",
        actor: str = "system",
    ) -> Orchestration:
        """Decisão humana da especificação quando o ciclo do §6 escalou (§4.4) — ação
        crítica, papel admin checado no handler da API (mesmo padrão de
        `decide_discovery`)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.spec_documents:
                raise KeyError("Nenhuma especificação para decidir.")
            spec = versao_atual(b.orchestration.spec_documents, SpecDocument)
            if spec.status != SPEC_STATUS_NECESSITA_HUMANO:
                raise ValueError(
                    f"Especificação não está aguardando decisão humana (status={spec.status})."
                )
            spec.status = SPEC_STATUS_APROVADO if approved else SPEC_STATUS_REPROVADO
            spec.revisao_comentarios = comentario
            b.orchestration.spec_documents = [
                *b.orchestration.spec_documents[:-1],
                spec.model_dump(mode="json"),
            ]
            b.orchestration.updated_at = now_iso()
            cards_criados = self._materialize_spec_cards(b, spec) if approved else []
            b.event_log.append(
                "SpecDecided",
                {
                    "orchestration_id": orchestration_id,
                    "approved": approved,
                    "actor": actor,
                    "cards_criados": len(cards_criados),
                },
            )
            self._persist(b)
            return b.orchestration

    def _materialize_spec_cards(self, b: OrchestrationBundle, spec: SpecDocument) -> list[str]:
        """Cria cards a partir de `spec.itens_de_trabalho` quando a especificação é
        aprovada (§5/§7/§10 do fluxo.md, ADR-0021) — mesmo padrão de
        `populate_from_plan`, com dependências resolvidas numa segunda passada.

        Domínio desconhecido é descartado (não trava a aprovação da spec por isso —
        diferente de `populate_from_plan`, que é síncrono com a criação da
        orquestração e pode recusar sem custo já pago).

        `itens_filhos` (§7, ADR-0025) vira `parent_id` — só um nível: cada item pode
        ter filhos diretos, o runtime não desce além disso. Cards-raiz nascem antes
        dos filhos para que `BoardService.add_card` encontre o pai já cadastrado.
        """
        if not spec.itens_de_trabalho:
            return []
        brief = DemandBrief.model_validate(b.orchestration.demand_brief)
        raizes: list[tuple[SpecWorkItem, KanbanCard]] = []
        filhos: list[tuple[SpecWorkItem, KanbanCard, str]] = []  # item, card, título do pai
        for item in spec.itens_de_trabalho:
            card = self._card_de_spec_item(b, brief, item)
            if card is None:
                continue
            raizes.append((item, card))
            for filho in item.itens_filhos:
                filho_card = self._card_de_spec_item(b, brief, filho)
                if filho_card is not None:
                    filhos.append((filho, filho_card, item.titulo))
        id_por_titulo = {item.titulo: card.id for item, card in raizes}
        id_por_titulo.update({item.titulo: card.id for item, card, _ in filhos})
        criados: list[str] = []
        for item, card in raizes:
            card.dependencies = [
                id_por_titulo[dep] for dep in item.depende_de if dep in id_por_titulo
            ]
            b.board_service.add_card(card)
            criados.append(card.id)
        for item, card, pai_titulo in filhos:
            card.parent_id = id_por_titulo.get(pai_titulo)
            card.dependencies = [
                id_por_titulo[dep] for dep in item.depende_de if dep in id_por_titulo
            ]
            b.board_service.add_card(card)
            criados.append(card.id)
        return criados

    def _card_de_spec_item(
        self, b: OrchestrationBundle, brief: DemandBrief, item: SpecWorkItem
    ) -> KanbanCard | None:
        """Constrói (sem persistir) o card de um item de trabalho da spec — domínio
        desconhecido devolve `None` (descartado pelo chamador)."""
        try:
            phase = Phase(item.fase)
        except ValueError:
            phase = Phase.F5
        assignee = _DOMAIN_AGENTS.get(item.dominio, item.dominio)
        if b.agent_registry.get(assignee) is None:
            return None
        return KanbanCard(
            board_id=b.board.id,
            orchestration_id=b.orchestration.id,
            phase=phase,
            type=_tipo_de_card(item.tipo),
            title=item.titulo,
            description=item.descricao,
            priority=prioridade_de(brief),
            assignee_type=AssigneeType.AGENT,
            assignee=assignee,
            status=ColumnKey.READY,
            acceptance_criteria=list(item.criterios_de_aceite),
        )

    def save_executor(self, profile: ExecutorProfile) -> list[dict[str, object]]:
        """Cria/atualiza um perfil de executor (tela de configurações) e persiste."""
        if self._catalog is None:
            self._catalog = ExecutorCatalog()
        self._catalog.upsert(profile)
        if self._executor_store is not None:
            self._executor_store.save(self._catalog.profiles())
        return self._catalog.entries()

    def delete_executor(self, name: str) -> list[dict[str, object]]:
        """Remove um perfil de executor (exceto 'mock') e persiste."""
        if self._catalog is None:
            return []
        self._catalog.remove(name)
        if self._executor_store is not None:
            self._executor_store.save(self._catalog.profiles())
        return self._catalog.entries()

    def _build_task(
        self,
        b: OrchestrationBundle,
        card: KanbanCard,
        agent: AgentSpec,
        *,
        effort: str | None = None,
    ) -> dict[str, Any]:
        section = agent.context_sections[0] if agent.context_sections else "engineering"
        nomes = self._naming.suggest(
            self._assignment(b, NAMING_KEY),
            card_type=card.type,
            title=card.title,
            description=card.description,
            acceptance_criteria=card.acceptance_criteria,
            phase=card.phase,
        )
        if nomes.fallback_reason:
            b.event_log.append(
                "NamingFallback",
                {"card_id": card.id, "reason": nomes.fallback_reason},
            )
        task: dict[str, Any] = {
            "orchestration_id": b.orchestration.id,
            "card_id": card.id,
            "phase": card.phase.value,
            "target_path": f"{section}.mock_{agent.role}",
            # Batismo do trabalho (ADR-0014): a branch sai do card, e o assunto do
            # commit vai no prompt para o agente CLI seguir a convenção. O sufixo de
            # unicidade é fechado por quem cria o worktree — o mesmo card pode ter
            # várias branches vivas (retry, candidatos concorrentes).
            "branch_stem": nomes.branch_stem,
            "commit_subject": nomes.commit_subject,
            "content": {
                "by": agent.role,
                "request": b.orchestration.user_request,
                # Sem estes campos o agente executava cego: recebia só a demanda global
                # da orquestração e nunca sabia QUAL card estava implementando.
                "card_title": card.title,
                "card_description": card.description,
                "card_type": card.type.value,
                "acceptance_criteria": list(card.acceptance_criteria),
                # Ações objetivas de uma revisão reprovada (§15, ADR-0017): sem isto o
                # agente re-executava cego, sem saber O QUE especificamente corrigir.
                "correction_actions": list(card.correction_actions),
                "commit_subject": nomes.commit_subject,
                "validation_command": b.orchestration.validation_command,
            },
        }
        if effort:
            task["effort"] = effort  # repassado ao agente (CLI/LLM) para calibrar o esforço
        return task

    def _execute_isolated(
        self,
        agent: AgentSpec,
        task: dict[str, Any],
        provider: ExecutionProvider | None = None,
    ) -> tuple[AgentOutput | None, list[DomainEvent], Exception | None]:
        """Executa o agente com supervisão (retry/nudge) em EventLog isolado (thread-safe)."""
        local = EventLog()
        supervisor = AgentSupervisor(provider or self._provider, event_log=local)
        start = time.perf_counter()
        card_id = task.get("card_id")
        try:
            output = supervisor.run(agent, task)
            ms = round((time.perf_counter() - start) * 1000, 1)
            uso = _uso_do_output(output)
            local.append(
                "AgentExecuted",
                {
                    "agent": agent.role,
                    "card_id": card_id,
                    "ms": ms,
                    "ok": True,
                    "tokens": uso.tokens_entrada + uso.tokens_saida,
                    "custo_usd": uso.custo_usd,
                    "modelo": uso.modelo,
                    "uso_origem": uso.origem,
                },
            )
            return output, local.all(), None
        except AgentExecutionError as exc:
            ms = round((time.perf_counter() - start) * 1000, 1)
            local.append(
                "AgentExecuted", {"agent": agent.role, "card_id": card_id, "ms": ms, "ok": False}
            )
            return None, local.all(), exc

    def _execute_wave(
        self,
        jobs: list[tuple[AgentSpec, dict[str, Any], ExecutionProvider | None]],
        concurrent: bool,
    ) -> list[tuple[AgentOutput | None, list[DomainEvent], Exception | None]]:
        """Executa uma onda; cada job traz o **seu** provider (a etapa do card decide qual)."""
        if concurrent and len(jobs) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
                return list(
                    pool.map(lambda job: self._execute_isolated(job[0], job[1], job[2]), jobs)
                )
        return [self._execute_isolated(agent, task, provider) for agent, task, provider in jobs]

    def _gasto_usd(self, b: OrchestrationBundle) -> float:
        """Custo real acumulado (§1.1, ADR-0026): soma `card.uso.custo_usd` de todo
        card do board — o mesmo número que o relatório de aprendizado usa."""
        return sum(float(c.uso.get("custo_usd", 0.0)) for c in b.board_service.cards_of(b.board.id))

    def _recusar_se_orcamento_estourado(self, b: OrchestrationBundle) -> None:
        """§3.2 do plano7: orçamento estourado recusa **execução nova**, nunca mata a
        que já está rodando — o freio vive na entrada de `run_card`/`race_card`, não
        num kill no meio da chamada."""
        situacao, motivo = avaliar_orcamento(self._gasto_usd(b), b.orchestration.orcamento_usd)
        if situacao == SITUACAO_ESTOURADO:
            raise ValueError(f"Orçamento estourado: {motivo}. Eleve o teto para continuar.")

    def _route_failure(
        self,
        b: OrchestrationBundle,
        card: KanbanCard,
        error: Exception | None,
        *,
        executor_atual: str,
        effort_atual: str | None,
    ) -> DecisaoDeFalha:
        """Registra a falha (§13), diagnostica e decide o roteamento (ADR-0019).

        Chamada de dentro do laço de `run_card`: a decisão pode mandar re-tentar (mesmo
        agente, effort maior, outro executor — o laço continua) ou parar (bloquear ou
        escalar humano). `run_plan` chama isto uma vez por card e ignora a decisão: a
        próxima onda simplesmente segue com o que sobrou.
        """
        mensagem = str(error) if error is not None else "execução não produziu saída"
        record = FailureRecord(
            etapa=ETAPA_EXECUCAO,
            tentativa=len(card.failures) + 1,
            comando=executor_atual,
            mensagem=mensagem,
            saida=mensagem,
            executor=executor_atual,
            effort=effort_atual or "",
        )
        card.failures = registrar(card.failures, record)
        diagnostico = diagnosticar(record)
        decisao = decidir(
            diagnostico,
            len(card.failures),
            executor_atual=executor_atual,
            effort_atual=effort_atual or "",
            catalogo=self._catalog,
            max_escalonamentos=self._max_escalonamentos,
        )
        # Freio de orçamento (§1.2/§3.2, ADR-0026): antes de gastar mais (effort maior
        # ou outro executor), confere o teto. Estourado vira `escalar_humano` — é
        # justamente quando as coisas já estão dando errado que a política, sem isto,
        # escalaria para o modelo mais caro sem ninguém olhar.
        if decisao.acao in (ACAO_AUMENTAR_EFFORT, ACAO_TROCAR_EXECUTOR):
            situacao, motivo_orcamento = avaliar_orcamento(
                self._gasto_usd(b), b.orchestration.orcamento_usd
            )
            if situacao == SITUACAO_ESTOURADO:
                decisao = DecisaoDeFalha(
                    acao=ACAO_ESCALAR_HUMANO, motivo=f"orçamento esgotado — {motivo_orcamento}"
                )
        # O motivo técnico (mensagem crua) continua visível no card — a política só
        # acrescenta o "por quê" da decisão, não substitui o erro real do agente.
        detalhe = f"{mensagem} — {decisao.motivo}"
        card.block_reason = detalhe
        # Nudge da política reaproveita o canal que `_build_task` já encaminha ao
        # agente (ADR-0017, `correction_actions`) — instrução concreta para a próxima
        # tentativa, seja ela dentro do mesmo `run_card` ou um retry manual depois.
        card.correction_actions = [decisao.nudge] if decisao.nudge else []
        b.event_log.append(
            "FailureRouted",
            {
                "card_id": card.id,
                "etapa": record.etapa,
                "diagnostico": diagnostico,
                "acao": decisao.acao,
                "tentativa": record.tentativa,
            },
        )
        # Mantido por compatibilidade: `aggregate_metrics` (db/repository.py) já conta
        # "AgentFailed" para a métrica `agent_failures` — `FailureRouted` acima é o
        # evento novo e mais rico, não uma substituição.
        b.event_log.append("AgentFailed", {"card_id": card.id, "error": mensagem})
        if decisao.acao == ACAO_BLOQUEAR:
            b.board_service.move_card(
                card.id,
                ColumnKey.BLOCKED,
                reason=detalhe,
                result="falhou",
                next_action=decisao.acao,
            )
        elif decisao.acao == ACAO_ESCALAR_HUMANO:
            b.board_service.move_card(
                card.id,
                ColumnKey.FAILED,
                reason=detalhe,
                result="falhou",
                next_action=decisao.acao,
            )
        else:
            b.board_service.move_card(
                card.id,
                card.status,
                reason=detalhe,
                result="falhou, nova tentativa automática",
                next_action=decisao.acao,
            )
        self._log.warning(
            "agent_failed",
            card_id=card.id,
            error=mensagem,
            diagnostico=diagnostico,
            acao=decisao.acao,
        )
        return decisao

    def _apply_execution(
        self,
        b: OrchestrationBundle,
        card_id: str,
        output: AgentOutput | None,
        events: list[DomainEvent],
        error: Exception | None,
        *,
        executor_name: str | None = None,
        catalog_executor: str | None = None,
        effort: str | None = None,
    ) -> tuple[list[BusResult], DecisaoDeFalha | None]:
        """Aplica serialmente (single-writer) o resultado de uma execução e move o card.

        Em falha, delega ao roteamento (ADR-0019): a `DecisaoDeFalha` devolvida diz a
        `run_card` se vale a pena tentar de novo dentro do mesmo laço (None = sucesso).
        `catalog_executor` é o nome do perfil no catálogo (distinto de `executor_name`,
        que é `provider.id` e pode vir prefixado `llm:` — ver `_catalog_name_of`); sem
        ele, cai em `executor_name`.
        """
        b.event_log.extend(events)
        b.board_service.apply_event(card_id, "AgentStarted")
        card = b.board_service.get_card(card_id)
        if card is None:
            return [], None
        if error is not None or output is None:
            decisao = self._route_failure(
                b,
                card,
                error,
                executor_atual=catalog_executor or executor_name or "",
                effort_atual=effort,
            )
            return [], decisao
        # Perfil de executor que de fato rodou (ADR-0017): distinto do papel
        # (`assignee`) — sem isto não há como exigir revisor diferente do card.
        if executor_name:
            card.executor = executor_name
        card.uso = acumular_uso(card.uso, _uso_do_output(output))
        branch = output.artifacts.get("branch")
        if branch:
            card.branch = str(branch)
        card.correction_actions = []  # sucesso: nudge/correções pendentes não se aplicam mais
        results = [self._submit_with_approval(b, p, card_id=card_id) for p in output.patches]
        if any(r.status == PatchStatus.REJECTED for r in results):
            b.board_service.move_card(card_id, ColumnKey.BLOCKED, reason="conflito detectado")
        elif any(r.status == PatchStatus.PENDING for r in results):
            b.board_service.apply_event(card_id, "AgentNeedsInput")  # → Waiting Human
        else:
            b.board_service.apply_event(card_id, "TestsPassed")  # → Testing
        return results, None

    def run_card(
        self,
        orchestration_id: str,
        card_id: str,
        *,
        provider: ExecutionProvider | None = None,
        effort: str | None = None,
    ) -> list[BusResult]:
        """Executa o agente do card (supervisionado), aplica patches e move o card.

        `provider`/`effort` permitem escolher o executor e o esforço por etapa. Em
        falha, o roteamento (ADR-0019) pode mandar re-tentar dentro deste mesmo laço
        (mesmo agente, effort maior, outro executor) antes de bloquear ou escalar —
        "retorna exatamente ao ponto responsável pelo erro" (§13 do fluxo.md).
        """
        b = self._bundle(orchestration_id)
        if b.orchestration.status == "cancelled":  # kill-switch (M6)
            raise ValueError("Orquestração cancelada: execução bloqueada.")
        self._recusar_se_orcamento_estourado(b)
        card = b.board_service.get_card(card_id)
        if card is None or card.assignee is None:
            raise KeyError(f"Card inválido ou sem agente: {card_id}")
        pendentes = self._pending_dependencies(b, card)
        if pendentes:
            card.blocked_by = [dep.id for dep in pendentes]
            titulos = ", ".join(dep.title for dep in pendentes)
            b.board_service.move_card(
                card_id, ColumnKey.BLOCKED, reason=f"aguardando dependência(s): {titulos}"
            )
            self._persist(b)
            raise ValueError(f"Card {card_id} tem dependência(s) pendente(s): {titulos}")
        if card.blocked_by:
            card.blocked_by = []  # dependências resolvidas: limpa o registro obsoleto
        agent = b.agent_registry.get(card.assignee)
        if agent is None:
            raise KeyError(f"Agente não registrado: {card.assignee}")
        # Chamada direta (ex.: /cards/{id}/run, /retry) sem provider → resolve pelo
        # executor da fase **do card** (não a fase corrente da orquestração: um retry
        # em F5 com a esteira já em F6 continua usando o agente configurado para F5).
        executor_atual = ""
        if provider is None:
            effort = self._effective_effort(b, None, effort, phase=card.phase)
            executor_atual = self._effective_executor(b, None, phase=card.phase) or ""
            provider = self._provider_for(b, None, effort, phase=card.phase)
        else:
            executor_atual = _catalog_name_of(provider)
        results: list[BusResult] = []
        output: AgentOutput | None = None
        error: Exception | None = None
        while True:
            task = self._build_task(b, card, agent, effort=effort)
            output, events, error = self._execute_isolated(agent, task, provider)
            executor_name = provider.id if provider is not None else None
            results, decisao = self._apply_execution(
                b,
                card_id,
                output,
                events,
                error,
                executor_name=executor_name,
                catalog_executor=executor_atual,
                effort=effort,
            )
            if error is None:
                break
            retentavel = (ACAO_MESMO_AGENTE, ACAO_AUMENTAR_EFFORT, ACAO_TROCAR_EXECUTOR)
            if decisao is None or decisao.acao not in retentavel:
                break
            if decisao.acao == ACAO_AUMENTAR_EFFORT and decisao.effort:
                effort = decisao.effort
            elif decisao.acao == ACAO_TROCAR_EXECUTOR and decisao.executor:
                executor_atual = decisao.executor
                provider = self.resolve_provider(
                    decisao.executor, target_path=b.orchestration.target_path, effort=effort
                )
        if error is None and output is not None and output.artifacts.get("branch"):
            self.open_pr(orchestration_id, card_id, branch=str(output.artifacts["branch"]))
        self._persist(b)
        return results

    def get_card_failures(self, orchestration_id: str, card_id: str) -> list[dict[str, object]]:
        """Histórico de falhas do card (§13, ADR-0019) — ring das últimas 5."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        return list(card.failures)

    def get_card_closure(self, orchestration_id: str, card_id: str) -> dict[str, object]:
        """Ficha de encerramento do card (§23, ADR-0021) — vazio = card ainda não
        encerrado (preenchida em `merge_pr`)."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        return dict(card.closure)

    def route_card(self, orchestration_id: str, card_id: str) -> list[BusResult]:
        """Aciona o roteamento de falha manualmente (ADR-0019) — para quando o
        automático parou por limite (`bloquear`/`escalar_humano`) e o operador já
        corrigiu a causa (ex.: ajustou o perfil do executor). Sem isto, "escalar para
        humano" seria um beco sem saída: `run_card` reaproveita o mesmo laço."""
        return self.run_card(orchestration_id, card_id)

    def _submit_with_approval(
        self, b: OrchestrationBundle, patch: ContextPatch, *, card_id: str | None = None
    ) -> BusResult:
        """Submete ao ContextBus; pendente → aprovação (§24); rejeitado → auto-resolução (§20)."""
        result = b.bus.submit(patch)
        if result.status == PatchStatus.PENDING:
            b.approvals.append(
                HumanApproval(
                    orchestration_id=b.orchestration.id,
                    card_id=card_id,
                    action=f"Aplicar patch em {patch.target_path}",
                    risk="high",
                    reason="Patch requer aprovação humana antes de aplicar.",
                    payload={"patch_id": patch.id},
                )
            )
            b.event_log.append("ApprovalRequested", {"patch_id": patch.id, "card_id": card_id})
        elif result.status == PatchStatus.REJECTED and result.conflict is not None:
            self._propose_resolution(b, result.conflict, auto=True)
        return result

    def run_plan(self, orchestration_id: str, *, concurrent: bool = True) -> dict[str, object]:
        """Executa o plano em ondas topológicas; agentes de uma onda rodam concorrentes (§13)."""
        b = self._bundle(orchestration_id)
        plan = b.plan
        cards_by_agent = {c.assignee: c for c in b.board_service.cards_of(b.board.id)}
        agents = {a.agent: a for a in plan.agents}
        done: set[str] = set()
        executed: list[str] = []
        waves = 0
        remaining = [a.agent for a in plan.agents]
        while remaining:
            wave = [
                n
                for n in remaining
                if all(d in done or d not in agents for d in agents[n].depends_on)
            ]
            if not wave:
                wave = [remaining[0]]  # quebra defensiva de ciclo
            jobs: list[tuple[str, AgentSpec, dict[str, Any], ExecutionProvider | None]] = []
            for name in wave:
                card = cards_by_agent.get(name)
                spec = b.agent_registry.get(name)
                if card is not None and spec is not None and card.status == ColumnKey.READY:
                    # Provider por card: cada um roda com o executor da **sua** etapa.
                    effort = self._effective_effort(b, None, None, phase=card.phase)
                    provider = self._provider_for(b, None, effort, phase=card.phase)
                    jobs.append(
                        (card.id, spec, self._build_task(b, card, spec, effort=effort), provider)
                    )
            outputs = self._execute_wave(
                [(spec, task, prov) for _c, spec, task, prov in jobs], concurrent
            )
            for (card_id, _s, _t, prov), (output, events, error) in zip(jobs, outputs, strict=True):
                executor_name = prov.id if prov is not None else None
                self._apply_execution(
                    b, card_id, output, events, error, executor_name=executor_name
                )
                executed.append(card_id)
            done.update(wave)
            remaining = [n for n in remaining if n not in done]
            waves += 1
        self._persist(b)
        return {
            "strategy": plan.strategy.value,
            "executed": executed,
            "count": len(executed),
            "waves": waves,
            "concurrent": concurrent,
        }

    @staticmethod
    def _agent_order(plan: ExecutionPlan) -> list[str]:
        """Ordem topológica dos agentes do plano por `depends_on` (workers antes do review)."""
        agents = {a.agent: a for a in plan.agents}
        order: list[str] = []
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited or name not in agents:
                return
            visited.add(name)
            for dep in agents[name].depends_on:
                visit(dep)
            order.append(name)

        for planned in plan.agents:
            visit(planned.agent)
        return order

    def run_quality_gate(
        self, orchestration_id: str, phase: Phase | None = None
    ) -> QualityGateResult:
        """Roda um quality gate simples e, se aprovado, gera snapshot da fase."""
        b = self._bundle(orchestration_id)
        target_phase = phase or b.orchestration.current_phase
        # Fase sem cards não trava o autopilot: o critério de output é vacuamente
        # aprovado quando não há trabalho naquela fase (ex.: F1–F4 sem /plan).
        has_work = any(c.phase == target_phase for c in b.board_service.cards_of(b.board.id))
        criteria = [
            Criterion(
                "context_has_output",
                lambda _c: (
                    b.store.version > 0 or not has_work,
                    "output aplicado" if has_work else "fase sem cards (vacuamente ok)",
                ),
            )
        ]
        # Discovery (§3/§4, ADR-0020): só entra quando um relatório foi de fato gerado
        # (`POST .../discovery/run`) — ring vazio (nunca rodado) não passa por aqui,
        # então nenhuma orquestração existente muda de comportamento no gate de F1.
        if target_phase == Phase.F1 and b.orchestration.discovery_reports:
            discovery_status = str(b.orchestration.discovery_reports[-1].get("status", ""))
            discovery_ok = discovery_status == STATUS_APROVADO
            criteria.append(
                Criterion(
                    "discovery_aprovado",
                    lambda _c: (discovery_ok, f"discovery {discovery_status or 'sem status'}"),
                )
            )
        # Implantação (§18-22, ADR-0023): só entra quando uma tentativa de
        # implantação de fato existe (`POST .../deploy/run`) — ring vazio
        # (nunca implantou) não passa por aqui, mesma prova de não-regressão
        # do critério `discovery_aprovado` acima.
        if target_phase == Phase.F6 and b.orchestration.deploy_runs:
            deploy_status = str(b.orchestration.deploy_runs[-1].get("aceite_status", ""))
            deploy_ok = deploy_status == ACEITE_APROVADO
            criteria.append(
                Criterion(
                    "deploy_aprovado",
                    lambda _c: (deploy_ok, f"implantação {deploy_status or 'sem status'}"),
                )
            )
        # Gate real (M5): nas fases de código, roda a bateria nomeada do §12 (ADR-0022)
        # — um Criterion por verificação, todos rodados até o fim (o `QualityGateEngine`
        # não interrompe no primeiro erro), então o gate sabe QUAL verificação falhou,
        # não só que "o comando falhou". Sem bateria configurada, `checks_efetivos` faz
        # o `validation_command` legado (ou `ASO_GATE_TEST_COMMAND`) virar uma única
        # verificação "testes" — nenhuma orquestração existente muda de comportamento.
        repo = b.orchestration.target_path or os.environ.get("ASO_TARGET_REPO")
        checks = checks_efetivos(b.orchestration)
        if not checks:
            gate_cmd_legado = os.environ.get("ASO_GATE_TEST_COMMAND")
            if gate_cmd_legado:
                checks = [ValidationCheck(nome=NOME_CHECK_LEGADO, comando=gate_cmd_legado)]
        if checks and repo and target_phase in (Phase.F5, Phase.F6):
            for check in checks:
                # `_check_predicate` fecha `comando` por parâmetro de fábrica — sem
                # isto, um `lambda` capturaria a variável do laço, e todo critério
                # rodaria o MESMO (o último) comando — armadilha clássica de closure
                # em `for` (§4.2/§5 do plano5.md).
                criteria.append(
                    Criterion(
                        check.nome,
                        _check_predicate(check.comando, repo),
                        blocking=check.bloqueante,
                    )
                )
        tem_validacao_configurada = bool(
            b.orchestration.validation_checks or b.orchestration.validation_command
        )
        if tem_validacao_configurada and target_phase in (Phase.F5, Phase.F6):
            criteria.append(
                Criterion(
                    "cards_entregues",
                    lambda _c: (
                        all(
                            c.status == ColumnKey.DONE
                            for c in b.board_service.cards_of(b.board.id)
                            if c.phase == target_phase
                        ),
                        "todos os cards foram mesclados"
                        if all(
                            c.status == ColumnKey.DONE
                            for c in b.board_service.cards_of(b.board.id)
                            if c.phase == target_phase
                        )
                        else "há cards sem merge governado",
                    ),
                )
            )
        # Drift contínuo de docs (NÃO-bloqueante): nas fases de código, avisa quando a
        # documentação docs-first ficou fora de sincronia com o código, sem reprovar o
        # gate — o operador sincroniza via "Sincronizar docs" (§ai-docs-self-healing).
        if repo and target_phase in (Phase.F5, Phase.F6):
            criteria.append(
                Criterion("docs_in_sync", lambda _c: _docs_sync_check(repo), blocking=False)
            )
        b.gate_engine.register(target_phase, criteria)
        result = b.gate_engine.run(target_phase, orchestration_id, b.store.get())
        if result.status == GateStatus.PASSED:
            version = f"O{target_phase.value[-1]}"
            snapshot = b.snapshot_engine.create(
                b.store,
                snapshot_version=version,
                phase=target_phase,
                frozen_sections=[],
                gate_result=result,
                adrs=[a.id for a in b.adr_registry.list_all()],
            )
            b.snapshots.append(snapshot)
            b.orchestration.snapshot_version = version
        b.gate_results.append(result)
        self._persist(b)
        return result

    # ---------------------------------------------------- workspace + docs-first
    def _docs_task(
        self, b: OrchestrationBundle, report: WorkspaceReport, *, effort: str | None = None
    ) -> dict[str, Any]:
        """Monta a tarefa (JSON via stdin) que instrui o agente a documentar docs-first."""
        acao = "atualizar (de forma localizada, sem recriar)" if report.has_aso_docs else "criar"
        modulos = ", ".join(report.detected_modules) or "(nenhum detectado)"
        instrucao = (
            "Documente este projeto no padrão docs-first (IA-first), em pt-BR. "
            f"Ação: {acao} a documentação em /docs. "
            "Estrutura obrigatória: docs/index.md (ponto de entrada que a IA lê antes do "
            "código) e docs/modules/<módulo>/<feature>.md. Cada feature deve conter as 8 "
            "seções: Descrição, Localização no código, Entrada, Saída, Dependências, "
            "Regras de negócio, Fluxo resumido, Possíveis erros. Leia o código para "
            "preencher com fatos reais, mantenha índices e links internos válidos e, se já "
            "houver documentação ASO, atualize sem recriar tudo. "
            f"Módulos detectados: {modulos}."
        )
        task: dict[str, Any] = {
            "orchestration_id": b.orchestration.id,
            "phase": Phase.F6.value,
            "target_path": "engineering.docs_first",
            "content": {"request": instrucao, "by": "DocumentationAgent"},
        }
        if effort:
            task["effort"] = effort
        return task

    def analyze_folder(
        self,
        orchestration_id: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
    ) -> dict[str, object]:
        """Analisa a pasta da orquestração e gera/atualiza a documentação docs-first.

        - Valida a pasta e garante repo git com HEAD (worktrees exigem HEAD).
        - Pasta vazia → escreve um scaffold determinístico (sem agente) e commita.
        - Projeto existente → o agente selecionado documenta em worktree isolado e o
          diff é mesclado (governado) na pasta; sem agente real, cai no scaffold.
        - Rede de segurança: garante ao menos a navegação docs-first mínima.
        - Registra evento + ContextPatch de resumo (rastreabilidade, sem aprovação —
          docs = baixo risco).
        """
        b = self._bundle(orchestration_id)
        tp = b.orchestration.target_path
        if not tp:
            raise ValueError("Orquestração sem pasta de trabalho (workspace) definida.")
        ws = WorkspaceService()
        root = ws.validate(tp)
        git_initialized = ws.ensure_git(root)
        report = WorkspaceAnalyzer(ws).analyze(root)

        created: list[str] = []
        mode: str
        if report.is_empty:
            mode = "scaffold"
            created = write_scaffold(root, report.detected_modules)
            ws.commit_all(root, "aso: docs-first (scaffold)")
        else:
            provider = self._provider_for(b, executor, effort)
            spec = b.agent_registry.get("DocumentationAgent")
            if (
                provider is not None
                and spec is not None
                and not isinstance(provider, LocalMockExecutionProvider)
            ):
                mode = "agent"
                task = self._docs_task(b, report, effort=effort)
                try:
                    output = provider.execute(spec, task)
                except AgentExecutionError as exc:
                    with self._lock_for(orchestration_id):
                        failed = self._bundle(orchestration_id)
                        failed.orchestration.workspace_prepared = False
                        failed.event_log.append(
                            "WorkspaceDocumentationFailed",
                            {
                                "orchestration_id": orchestration_id,
                                "executor": executor or failed.orchestration.selected_executor,
                                "reason": str(exc)[:500],
                            },
                        )
                        self._persist(failed)
                    raise WorkspaceError(f"Falha ao documentar com o agente: {exc}") from exc
                branch = output.artifacts.get("branch")
                if branch:
                    try:
                        WorktreeManager(str(root)).merge(str(branch))
                    except WorktreeError:
                        # Agente não gerou diff mesclável — a rede de segurança cobre.
                        pass
            else:
                mode = "scaffold"
                created = write_scaffold(root, report.detected_modules)
                ws.commit_all(root, "aso: docs-first (scaffold)")

        after = WorkspaceAnalyzer(ws).analyze(root)
        if not after.has_aso_docs:
            # Rede de segurança: garante docs/index.md + docs/modules/ navegáveis.
            extra = write_scaffold(root, after.detected_modules)
            if extra:
                created += extra
                ws.commit_all(root, "aso: docs-first (scaffold de segurança)")
                after = WorkspaceAnalyzer(ws).analyze(root)

        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            b.orchestration.workspace_prepared = True
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "WorkspaceAnalyzed",
                {
                    "orchestration_id": orchestration_id,
                    "path": str(root),
                    "mode": mode,
                    "has_aso_docs": after.has_aso_docs,
                    "git_initialized": git_initialized,
                },
            )
            patch = ContextPatch(
                orchestration_id=orchestration_id,
                agent="DocumentationAgent",
                phase=b.orchestration.current_phase,
                patch_type=PatchType.UPDATE,
                target_path="engineering.docs_first",
                content={
                    "path": str(root),
                    "mode": mode,
                    "created": created,
                    "detected_modules": after.detected_modules,
                    "has_aso_docs": after.has_aso_docs,
                },
                evidence=[f"mode={mode}", f"has_aso_docs={after.has_aso_docs}"],
            )
            b.bus.submit(patch)
            self._persist(b)
        self._log.info(
            "workspace_analyzed",
            orchestration_id=orchestration_id,
            mode=mode,
            has_aso_docs=after.has_aso_docs,
        )
        return {
            "path": str(root),
            "mode": mode,
            "git_initialized": git_initialized,
            "created": created,
            "report": after.model_dump(),
        }

    def docs_drift(self, orchestration_id: str) -> dict[str, object]:
        """Relatório determinístico (só leitura) do drift docs↔código do workspace."""
        b = self._bundle(orchestration_id)
        tp = b.orchestration.target_path
        if not tp:
            raise ValueError("Orquestração sem pasta de trabalho (workspace) definida.")
        return check_drift(tp).model_dump()

    # ------------------------------------------------------------- próximo passo
    def next_step(
        self, orchestration_id: str, *, slo_breaches: list[str] | None = None
    ) -> NextStepReport:
        """Diz o que falta para a esteira seguir (§14 · ADR-0013).

        Coleta o retrato do estado governado e delega o cálculo ao motor puro em
        `control/next_step.py` — assim a UI não reimplementa regra de governança.
        Sinais externos que não vivem no bundle (drift de docs, SLO) entram como
        entrada opcional e nunca derrubam a leitura.
        """
        b = self._bundle(orchestration_id)
        drift: DocsDriftReport | None = None
        if b.orchestration.target_path:
            try:
                drift = check_drift(b.orchestration.target_path)
            except (OSError, WorkspaceError):  # pasta sumiu/sem permissão: segue sem o sinal
                drift = None
        available, reason = self._executor_availability(b.orchestration.selected_executor)
        return compute_next_step(
            NextStepInput(
                orchestration=b.orchestration,
                demand_brief=DemandBrief.model_validate(b.orchestration.demand_brief),
                discovery_report=versao_atual(b.orchestration.discovery_reports, DiscoveryReport),
                spec=versao_atual(b.orchestration.spec_documents, SpecDocument),
                deploy=versao_atual(b.orchestration.deploy_runs, DeployRun),
                candidate_runs=list(b.candidate_runs),
                cards=b.board_service.cards_of(b.board.id),
                approvals=list(b.approvals),
                pulls=list(b.pull_requests),
                conflicts=list(b.bus.conflicts),
                gate_results=list(b.gate_results),
                drift=drift,
                executor_available=available,
                executor_reason=reason,
                slo_breaches=list(slo_breaches or []),
                gasto_usd=self._gasto_usd(b),
                agent_timeout_seconds=CLI_AGENT_TIMEOUT_PADRAO,
            )
        )

    def _executor_availability(self, name: str | None) -> tuple[bool | None, str]:
        """Disponibilidade do executor escolhido (None = catálogo não configurado)."""
        if self._catalog is None or not name:
            return None, ""
        entry = next((e for e in self._catalog.entries() if e.get("name") == name), None)
        if entry is None:
            return False, f"Executor '{name}' não está mais no catálogo."
        if entry.get("available"):
            return True, str(entry.get("runtime_version") or "")
        return False, str(entry.get("availability_reason") or "Executor indisponível.")

    def _docs_heal_task(
        self, b: OrchestrationBundle, drift: DocsDriftReport, *, effort: str | None = None
    ) -> dict[str, Any]:
        """Tarefa (JSON via stdin) que instrui o agente a sincronizar docs com o código."""
        partes: list[str] = []
        if drift.undocumented_modules:
            partes.append(
                "crie docs/modules/<módulo>/<feature>.md para: "
                + ", ".join(drift.undocumented_modules)
            )
        if drift.orphan_module_docs:
            partes.append(
                "revise/remova docs de módulos que não existem mais no código: "
                + ", ".join(drift.orphan_module_docs)
            )
        if drift.broken_links:
            partes.append(
                "conserte os links internos quebrados: " + "; ".join(drift.broken_links[:20])
            )
        if drift.unfilled_features:
            partes.append(
                "preencha, com fatos reais do código, as docs ainda em placeholder: "
                + ", ".join(drift.unfilled_features[:20])
            )
        instrucao = (
            "Sincronize a documentação docs-first (IA-first) com o código atual, em pt-BR, "
            "de forma LOCALIZADA (não recrie tudo). Mantenha o template de 8 seções por "
            "feature (Descrição, Localização no código, Entrada, Saída, Dependências, "
            "Regras de negócio, Fluxo resumido, Possíveis erros), o índice e os links "
            "internos válidos. Pontos de drift a resolver: " + "; ".join(partes) + "."
        )
        task: dict[str, Any] = {
            "orchestration_id": b.orchestration.id,
            "phase": Phase.F6.value,
            "target_path": "engineering.docs_drift",
            "content": {"request": instrucao, "by": "DocumentationAgent"},
        }
        if effort:
            task["effort"] = effort
        return task

    def heal_docs(
        self,
        orchestration_id: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
    ) -> dict[str, object]:
        """Sincroniza (self-heal) a documentação docs-first com o código do workspace.

        - Determinístico: cria `docs/modules/<módulo>/` para módulos de código sem doc.
        - Agente (se houver executor real): preenche placeholders e conserta links num
          worktree isolado, com o diff mesclado (governado).
        - Registra evento `DocsHealed` + ContextPatch (`engineering.docs_drift`).
        """
        b = self._bundle(orchestration_id)
        tp = b.orchestration.target_path
        if not tp:
            raise ValueError("Orquestração sem pasta de trabalho (workspace) definida.")
        ws = WorkspaceService()
        root = ws.validate(tp)
        ws.ensure_git(root)
        before = check_drift(root, ws)

        healed: list[str] = []
        mode = "noop"
        if before.has_drift:
            if before.undocumented_modules:
                created = write_scaffold(root, before.undocumented_modules)
                if created:
                    healed += created
                    ws.commit_all(root, "aso: docs-first (módulos sem doc)")
                    mode = "scaffold"
            provider = self._provider_for(b, executor, effort)
            spec = b.agent_registry.get("DocumentationAgent")
            if (
                provider is not None
                and spec is not None
                and not isinstance(provider, LocalMockExecutionProvider)
            ):
                task = self._docs_heal_task(b, before, effort=effort)
                try:
                    output = provider.execute(spec, task)
                except AgentExecutionError as exc:
                    raise WorkspaceError(f"Falha ao sincronizar docs com o agente: {exc}") from exc
                branch = output.artifacts.get("branch")
                if branch:
                    try:
                        WorktreeManager(str(root)).merge(str(branch))
                        mode = "agent"
                    except WorktreeError:
                        # Agente não gerou diff mesclável — o scaffold determinístico cobre.
                        pass

        after = check_drift(root, ws)
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DocsHealed",
                {
                    "orchestration_id": orchestration_id,
                    "mode": mode,
                    "had_drift": before.has_drift,
                    "has_drift": after.has_drift,
                },
            )
            patch = ContextPatch(
                orchestration_id=orchestration_id,
                agent="DocumentationAgent",
                phase=b.orchestration.current_phase,
                patch_type=PatchType.UPDATE,
                target_path="engineering.docs_drift",
                content={
                    "mode": mode,
                    "healed": healed,
                    "before": before.model_dump(),
                    "after": after.model_dump(),
                },
                evidence=[
                    f"mode={mode}",
                    f"had_drift={before.has_drift}",
                    f"has_drift={after.has_drift}",
                ],
            )
            b.bus.submit(patch)
            self._persist(b)
        self._log.info(
            "docs_healed",
            orchestration_id=orchestration_id,
            mode=mode,
            has_drift=after.has_drift,
        )
        return {
            "path": str(root),
            "mode": mode,
            "healed": healed,
            "before": before.model_dump(),
            "after": after.model_dump(),
        }

    def _maybe_autoheal_docs(
        self,
        orchestration_id: str,
        phase: Phase,
        executor: str | None,
        effort: str | None,
    ) -> dict[str, object] | None:
        """Ao fim de F5/F6, sincroniza docs-first automaticamente quando há drift.

        Best-effort: nunca derruba a fase/autopilot. Só roda quando há pasta, docs
        geradas e drift real. Pode ser desligado com `ASO_AUTOHEAL_DOCS=0`.
        """
        if os.environ.get("ASO_AUTOHEAL_DOCS", "1") == "0":
            return None
        if phase not in (Phase.F5, Phase.F6):
            return None
        tp = self._bundle(orchestration_id).orchestration.target_path
        if not tp:
            return None
        try:
            drift = check_drift(tp)
        except ValueError:
            return None
        if not (drift.has_docs and drift.has_drift):
            return None
        try:
            result = self.heal_docs(orchestration_id, executor=executor, effort=effort)
        except (WorkspaceError, ValueError) as exc:  # não derruba a esteira
            self._log.warning(
                "autoheal_docs_failed", orchestration_id=orchestration_id, error=str(exc)
            )
            return None
        self._log.info("autoheal_docs", orchestration_id=orchestration_id, mode=result.get("mode"))
        return result

    # ------------------------------------------------------------- autopilot (M3)
    def run_phase(
        self,
        orchestration_id: str,
        phase: Phase | None = None,
        *,
        executor: str | None = None,
        effort: str | None = None,
    ) -> dict[str, object]:
        """Executa uma fase ponta a ponta: roda os cards Ready da fase, roda o gate,
        gera snapshot (se aprovado) e abre uma aprovação humana de avanço de fase (§8.6).

        `executor`/`effort` escolhem o agente e o esforço desta etapa; a escolha é
        guardada na aprovação para o auto-avanço (M4) manter a mesma configuração.
        """
        # Resolve o provider da **etapa** (ADR-0014), já atrelado à pasta (workspace).
        b0 = self._bundle(orchestration_id)
        target = phase or b0.orchestration.current_phase
        effective_executor = self._effective_executor(b0, executor, phase=target)
        effort = self._effective_effort(b0, effective_executor, effort, phase=target)
        provider = self._provider_for(b0, effective_executor, effort, phase=target)
        # Sem esforço explícito, herda o esforço do perfil do executor efetivo
        # (o escolhido ou, quando há pasta, o default do catálogo).
        if effort is None and self._catalog is not None:
            name_for_effort = effective_executor or (
                self._catalog.default_name() if b0.orchestration.target_path else None
            )
            if name_for_effort:
                prof = self._catalog.get(name_for_effort)
                if prof is not None and prof.effort:
                    effort = prof.effort
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if b.orchestration.status == "cancelled":  # kill-switch (M6)
                raise ValueError("Orquestração cancelada: execução bloqueada.")
            # F5 não começa sem especificação aprovada em full-pipeline (§5/§6, ADR-0021)
            # — só quando o fluxo de discovery foi de fato usado (mesma regra de
            # não-regressão do critério de gate da ADR-0020 §6): orquestrações que
            # nunca chamam /discovery/run (a maioria da suíte pré-existente, e todo
            # CODE_EXECUTION) não mudam de comportamento em F5.
            exige_spec = (
                target == Phase.F5
                and b.orchestration.execution_mode == ExecutionMode.FULL_PIPELINE
                and bool(b.orchestration.discovery_reports)
            )
            if exige_spec:
                spec_atual = versao_atual(b.orchestration.spec_documents, SpecDocument)
                if spec_atual.status not in SPEC_STATUS_APROVADOS:
                    raise ValueError(
                        "F5 não começa sem especificação aprovada (§5/§6 do fluxo.md) — "
                        f"status atual: '{spec_atual.status or 'nunca gerada'}'."
                    )
            card_ids = [
                c.id
                for c in b.board_service.cards_of(b.board.id)
                if c.phase == target and c.status == ColumnKey.READY
            ]

        ran: list[str] = []
        failed: list[str] = []
        for cid in card_ids:
            try:
                self.run_card(orchestration_id, cid, provider=provider, effort=effort)
                card = self._bundle(orchestration_id).board_service.get_card(cid)
                if card is not None and card.status == ColumnKey.FAILED:
                    failed.append(cid)
                else:
                    ran.append(cid)
            except Exception:  # noqa: BLE001 — card inválido não derruba a fase inteira
                failed.append(cid)

        if self._bundle(orchestration_id).orchestration.validation_command and target in (
            Phase.F5,
            Phase.F6,
        ):
            phase_cards = [
                c
                for c in self._bundle(orchestration_id).board_service.cards_of(b.board.id)
                if c.phase == target
            ]
            if any(c.status != ColumnKey.DONE for c in phase_cards):
                self._bundle(orchestration_id).event_log.append(
                    "PhaseAwaitingDelivery", {"phase": target.value, "cards_failed": failed}
                )
                self._persist(self._bundle(orchestration_id))
                return {
                    "phase": target.value,
                    "cards_ran": ran,
                    "cards_failed": failed,
                    "gate_status": "WAITING_DELIVERY",
                    "snapshot": None,
                    "approval_id": None,
                    "next_phase": target.value,
                }

        gate = self.run_quality_gate(orchestration_id, target)
        # Self-heal automático da documentação docs-first ao fim de F5/F6 (§ADR-0012).
        autoheal = self._maybe_autoheal_docs(orchestration_id, target, effective_executor, effort)
        approval_id: str | None = None
        snapshot: str | None = None
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if gate.status == GateStatus.PASSED:
                snapshot = b.orchestration.snapshot_version
                approval = HumanApproval(
                    orchestration_id=orchestration_id,
                    action=f"Aprovar avanço da fase {target.value}",
                    risk="medium",
                    reason=f"Fase {target.value} concluída (gate PASSED): "
                    f"{len(ran)} cards executados.",
                    payload={
                        "kind": "phase_gate",
                        "phase": target.value,
                        "executor": executor,
                        "effort": effort,
                    },
                )
                b.approvals.append(approval)
                approval_id = approval.id
            b.event_log.append(
                "PhaseCompleted",
                {"phase": target.value, "cards": len(ran), "gate": gate.status.value},
            )
            self._persist(b)
            nxt = self._next_phase(target)
        self._log.info(
            "phase_completed",
            orchestration_id=orchestration_id,
            phase=target.value,
            gate=gate.status.value,
            cards_ran=len(ran),
            cards_failed=len(failed),
        )
        return {
            "phase": target.value,
            "cards_ran": ran,
            "cards_failed": failed,
            "gate_status": gate.status.value,
            "snapshot": snapshot,
            "approval_id": approval_id,
            "next_phase": nxt.value if nxt else None,
            "docs_autoheal": autoheal,
        }

    @staticmethod
    def _next_phase(phase: Phase) -> Phase | None:
        order = list(Phase)
        idx = order.index(phase)
        return order[idx + 1] if idx + 1 < len(order) else None

    def advance_phase(self, orchestration_id: str) -> Orchestration:
        """Avança a orquestração para a próxima fase (F1→…→F7). Ação governada."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            nxt = self._next_phase(b.orchestration.current_phase)
            if nxt is None:
                raise ValueError("Já está na última fase (F7); não há próxima.")
            b.orchestration.current_phase = nxt
            b.event_log.append("PhaseAdvanced", {"to": nxt.value})
            self._persist(b)
            return b.orchestration
