"""`BundleStore` — cache, hidratação, persistência e lock dos agregados (ADR-0066, MEL-32 passo 1).

Antes, `OrchestrationService` misturava essas responsabilidades com ~260 métodos de caso de
uso, e a disciplina de lock variava de método para método. Aqui fica a **fonte única** do lock
por orquestração: todo serviço de aplicação lê o bundle e muta sob `lock_for`, e persiste por
`persist` (que também serializa sob o mesmo lock).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from aso.agents.models import AgentDefinition
from aso.agents.registry import AgentRegistry
from aso.control.models import ExecutionPlan, Orchestration
from aso.governance.adr_registry import ADRRegistry
from aso.governance.context_store import OrchestratorContextStore
from aso.governance.contextbus import ContextBus, PermissionPolicy
from aso.governance.models import (
    BugReport,
    CandidateRun,
    HumanApproval,
    Incident,
    PullRequest,
    QualityGateResult,
    ReviewComment,
    SloEvaluation,
    Snapshot,
)
from aso.governance.quality_gate_engine import QualityGateEngine
from aso.governance.snapshot_engine import SnapshotEngine
from aso.kanban.board_service import BoardService
from aso.kanban.models import Board
from aso.persistence.ports import OrchestrationRepository
from aso.persistence.state import OrchestrationState
from aso.shared.cache import TTLCache
from aso.shared.events import DomainEvent, EventLog


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
    incidents: list[Incident] = field(default_factory=list)
    bug_reports: list[BugReport] = field(default_factory=list)
    review_comments: list[ReviewComment] = field(default_factory=list)


class BundleStore:
    """Fonte única de bundles hidratados e de locks por orquestração."""

    def __init__(
        self,
        repository: OrchestrationRepository,
        *,
        definicoes_ativas: Callable[[], list[AgentDefinition]],
        read_cache: TTLCache | None = None,
        ao_hidratar: Callable[[OrchestrationBundle], None] | None = None,
    ) -> None:
        self.repository = repository
        self._definicoes_ativas = definicoes_ativas
        self._read_cache = read_cache
        self.ao_hidratar = ao_hidratar
        # Cache de agregados. Exposto (mesmo objeto) para compatibilidade da façade.
        self.cache: dict[str, OrchestrationBundle] = {}
        # Locks por orquestração: serializam ler-bundle → mutar → persistir sob requisições
        # concorrentes (API/CLI multithread) — evita lost-update e dupla hidratação.
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def lock_for(self, orchestration_id: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._locks.get(orchestration_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[orchestration_id] = lock
            return lock

    def get(self, orchestration_id: str) -> OrchestrationBundle:
        bundle = self.cache.get(orchestration_id)
        if bundle is not None:
            return bundle
        # Double-checked locking: sem isto, duas requisições concorrentes para uma
        # orquestração ainda não cacheada hidratam instâncias divergentes e a segunda
        # escrita sobrescreve a primeira (lost-update). Garante instância única.
        with self.lock_for(orchestration_id):
            bundle = self.cache.get(orchestration_id)
            if bundle is not None:
                return bundle
            state = self.repository.load(orchestration_id)
            if state is None:
                raise KeyError(f"Orquestração inexistente: {orchestration_id}")
            bundle = self.hydrate(state)
            self.cache[orchestration_id] = bundle
            if self.ao_hidratar is not None:
                self.ao_hidratar(bundle)
            return bundle

    def put(self, bundle: OrchestrationBundle) -> None:
        self.cache[bundle.orchestration.id] = bundle

    def persist(self, bundle: OrchestrationBundle) -> None:
        # Serializa a serialização+save por orquestração: `to_state` lê todo o bundle e o
        # repositório grava níveis por FK; concorrência aqui gera estado persistido
        # inconsistente. RLock reentrante (o chamador pode já o deter).
        with self.lock_for(bundle.orchestration.id):
            self.repository.save(self.to_state(bundle))
            if self._read_cache is not None:
                self._read_cache.clear()  # invalida agregações após escrita

    @staticmethod
    def to_state(b: OrchestrationBundle) -> OrchestrationState:
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
            incidents=list(b.incidents),
            bug_reports=list(b.bug_reports),
            review_comments=list(b.review_comments),
            board=b.board,
            cards=b.board_service.cards_of(b.board.id),
            card_events=list(b.board_service.card_events),
            events=[
                {"type": e.type, "payload": e.payload, "created_at": e.created_at}
                for e in b.event_log.all()
            ],
        )

    def hydrate(self, state: OrchestrationState) -> OrchestrationBundle:
        oid = state.orchestration.id
        events = EventLog()
        events.seed(
            [
                DomainEvent(type=e["type"], payload=e["payload"], created_at=e["created_at"])
                for e in state.events
            ]
        )
        registry = AgentRegistry()
        registry.seed_from_catalog(self._definicoes_ativas())

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
            incidents=list(state.incidents),
            bug_reports=list(state.bug_reports),
            review_comments=list(state.review_comments),
        )
