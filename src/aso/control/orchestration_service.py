"""OrchestrationService (Control Plane).

Amarra os planes do runtime: cria orquestrações, gera ExecutionPlan, monta o
OrchestratorContext, o board Kanban e os cards, executa agentes (mock), submete
patches ao ContextBus, roda quality gate e gera snapshot. É o ponto de entrada
usado por API e CLI.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

from aso.agents.executor import AgentExecutionError, ExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.agents.registry import AgentRegistry
from aso.agents.supervisor import AgentSupervisor
from aso.control.decision_engine import MultiAgentDecisionEngine
from aso.control.execution_planner import ExecutionPlanner
from aso.control.models import DecisionInput, ExecutionPlan, Orchestration
from aso.execution.candidates import CandidateRunner
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
    Snapshot,
)
from aso.governance.quality_gate_engine import Criterion, QualityGateEngine
from aso.governance.snapshot_engine import SnapshotEngine
from aso.kanban.board_service import BoardService
from aso.kanban.models import Board, KanbanCard
from aso.persistence.memory import InMemoryOrchestrationRepository
from aso.persistence.ports import OrchestrationRepository
from aso.persistence.state import OrchestrationState
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
    Phase,
)


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


class OrchestrationService:
    """Serviço in-memory de orquestrações (MVP-1, sem persistência)."""

    def __init__(
        self,
        provider: ExecutionProvider | None = None,
        repository: OrchestrationRepository | None = None,
        *,
        max_races_per_card: int | None = None,
    ) -> None:
        self._bundles: dict[str, OrchestrationBundle] = {}
        self._provider = provider
        self._repo: OrchestrationRepository = repository or InMemoryOrchestrationRepository()
        self._read_cache = TTLCache(ttl_seconds=1.0)  # cache de leitura para agregações
        # Retenção de corridas por card: evita o candidate_runs crescer sem limite.
        self._max_races_per_card = (
            max_races_per_card
            if max_races_per_card is not None
            else int(os.environ.get("ASO_MAX_RACES_PER_CARD", "20"))
        )
        # Locks por orquestração: serializam ler-bundle → mutar → persistir sob
        # requisições concorrentes (API/CLI multithread) — evita lost-update e
        # dupla hidratação (achados de concorrência 1.1/4.1). RLock = reentrante.
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

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
        execution_mode: ExecutionMode = ExecutionMode.FULL_PIPELINE,
        decision_input: DecisionInput | None = None,
    ) -> Orchestration:
        orchestration = Orchestration(
            project_id=project_id, execution_mode=execution_mode, user_request=user_request
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

        # Cria um card por agente planejado.
        for planned in plan.agents:
            card = KanbanCard(
                board_id=board.id,
                orchestration_id=oid,
                phase=orchestration.current_phase,
                type=CardType.TASK,
                title=f"{planned.agent}: {planned.reason or planned.role}",
                assignee_type=AssigneeType.AGENT,
                assignee=planned.agent,
                status=ColumnKey.READY,
                acceptance_criteria=["Output do agente aplicado via ContextBus"],
            )
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
        )

    def get(self, orchestration_id: str) -> Orchestration:
        return self._bundle(orchestration_id).orchestration

    def list_all(self) -> list[Orchestration]:
        # Leitura leve: consulta a tabela de orquestrações, sem hidratar aggregates.
        return self._repo.list_orchestrations()[0]

    def list_orchestrations_page(self, *, page: int = 1, page_size: int = 50) -> dict[str, object]:
        page = max(page, 1)
        items, total = self._repo.list_orchestrations(
            limit=page_size, offset=(page - 1) * page_size
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

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
        pr = PullRequest(
            orchestration_id=orchestration_id,
            card_id=card_id,
            branch=branch or card.branch or f"aso/{card_id}",
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
        b = self._bundle(orchestration_id)
        pr = self._find_pr(b, pr_id)
        pr.ci_status = status
        if status == "failed" and pr.card_id and b.board_service.get_card(pr.card_id):
            b.board_service.apply_event(pr.card_id, "CIFailed")  # → Failed
        b.event_log.append("CIReported", {"pr_id": pr_id, "status": status})
        self._persist(b)
        return pr

    def report_review(self, orchestration_id: str, pr_id: str, status: str) -> PullRequest:
        b = self._bundle(orchestration_id)
        pr = self._find_pr(b, pr_id)
        pr.review_status = status
        if status == "changes_requested" and pr.card_id and b.board_service.get_card(pr.card_id):
            b.board_service.apply_event(pr.card_id, "ReviewRequestedChanges")  # → Review
        b.event_log.append("ReviewReported", {"pr_id": pr_id, "status": status})
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
            worktree = getattr(self._provider, "worktree", None)
            if worktree is not None:
                worktree.merge(pr.branch)  # merge git real na branch base
            pr.status = "merged"
            pr.merged_at = now_iso()
            if pr.card_id and b.board_service.get_card(pr.card_id):
                b.board_service.apply_event(pr.card_id, "QualityGatePassed")  # → Done
            b.event_log.append("PRMerged", {"pr_id": pr_id, "branch": pr.branch})
        self._persist(b)
        return pr

    def list_pulls(self, orchestration_id: str) -> list[PullRequest]:
        return list(self._bundle(orchestration_id).pull_requests)

    def race_card(
        self, orchestration_id: str, card_id: str, providers: list[ExecutionProvider]
    ) -> dict[str, object]:
        """Roda múltiplos agentes CLI em paralelo por card e compara os diffs (§26A.6)."""
        b = self._bundle(orchestration_id)
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
            return approval

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

    def resume(self, orchestration_id: str) -> Orchestration:
        b = self._bundle(orchestration_id)
        b.orchestration.status = "running"
        b.event_log.append("OrchestrationResumed", {"orchestration_id": orchestration_id})
        self._persist(b)
        return b.orchestration

    def retry(self, orchestration_id: str) -> list[str]:
        """Reexecuta cards pendentes/falhos (§28.1). Retorna os ids reexecutados."""
        b = self._bundle(orchestration_id)
        retryable = {ColumnKey.READY, ColumnKey.FAILED, ColumnKey.BLOCKED}
        targets = [c.id for c in b.board_service.cards_of(b.board.id) if c.status in retryable]
        for card_id in targets:
            self.run_card(orchestration_id, card_id)
        return targets

    def snapshot_diff(self, orchestration_id: str, from_v: str, to_v: str) -> dict[str, object]:
        b = self._bundle(orchestration_id)
        sa = b.snapshot_engine.get(from_v)
        sb = b.snapshot_engine.get(to_v)
        if sa is None or sb is None:
            raise KeyError(f"Snapshot inexistente: {from_v if sa is None else to_v}")
        fa, fb = set(sa.frozen_sections), set(sb.frozen_sections)
        keys = set(sa.payload) | set(sb.payload)
        changed = [k for k in keys if sa.payload.get(k) != sb.payload.get(k)]
        return {
            "from": from_v,
            "to": to_v,
            "frozen_added": sorted(fb - fa),
            "frozen_removed": sorted(fa - fb),
            "changed_sections": sorted(changed),
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
        self, orchestration_id: str, *, page: int = 1, page_size: int = 50
    ) -> dict[str, object]:
        self._bundle(orchestration_id)  # valida existência (404 se não existir)
        page = max(page, 1)
        items, total = self._repo.events_page(
            orchestration_id, limit=page_size, offset=(page - 1) * page_size
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    # ------------------------------------------------------------------ execução
    def _build_task(
        self, b: OrchestrationBundle, card: KanbanCard, agent: AgentSpec
    ) -> dict[str, Any]:
        section = agent.context_sections[0] if agent.context_sections else "engineering"
        return {
            "orchestration_id": b.orchestration.id,
            "card_id": card.id,
            "phase": b.orchestration.current_phase.value,
            "target_path": f"{section}.mock_{agent.role}",
            "content": {"by": agent.role, "request": b.orchestration.user_request},
        }

    def _execute_isolated(
        self, agent: AgentSpec, task: dict[str, Any]
    ) -> tuple[AgentOutput | None, list[DomainEvent], Exception | None]:
        """Executa o agente com supervisão (retry/nudge) em EventLog isolado (thread-safe)."""
        local = EventLog()
        supervisor = AgentSupervisor(self._provider, event_log=local)
        start = time.perf_counter()
        card_id = task.get("card_id")
        try:
            output = supervisor.run(agent, task)
            ms = round((time.perf_counter() - start) * 1000, 1)
            local.append(
                "AgentExecuted", {"agent": agent.role, "card_id": card_id, "ms": ms, "ok": True}
            )
            return output, local.all(), None
        except AgentExecutionError as exc:
            ms = round((time.perf_counter() - start) * 1000, 1)
            local.append(
                "AgentExecuted", {"agent": agent.role, "card_id": card_id, "ms": ms, "ok": False}
            )
            return None, local.all(), exc

    def _execute_wave(
        self, jobs: list[tuple[AgentSpec, dict[str, Any]]], concurrent: bool
    ) -> list[tuple[AgentOutput | None, list[DomainEvent], Exception | None]]:
        if concurrent and len(jobs) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
                return list(pool.map(lambda job: self._execute_isolated(*job), jobs))
        return [self._execute_isolated(*job) for job in jobs]

    def _apply_execution(
        self,
        b: OrchestrationBundle,
        card_id: str,
        output: AgentOutput | None,
        events: list[DomainEvent],
        error: Exception | None,
    ) -> list[BusResult]:
        """Aplica serialmente (single-writer) o resultado de uma execução e move o card."""
        b.event_log.extend(events)
        b.board_service.apply_event(card_id, "AgentStarted")
        if error is not None or output is None:
            b.board_service.apply_event(card_id, "CIFailed")  # → Failed
            b.event_log.append("AgentFailed", {"card_id": card_id, "error": str(error)})
            return []
        branch = output.artifacts.get("branch")
        if branch:
            card = b.board_service.get_card(card_id)
            if card is not None:
                card.branch = str(branch)
        results = [self._submit_with_approval(b, p, card_id=card_id) for p in output.patches]
        if any(r.status == PatchStatus.REJECTED for r in results):
            b.board_service.move_card(card_id, ColumnKey.BLOCKED, reason="conflito detectado")
        elif any(r.status == PatchStatus.PENDING for r in results):
            b.board_service.apply_event(card_id, "AgentNeedsInput")  # → Waiting Human
        else:
            b.board_service.apply_event(card_id, "TestsPassed")  # → Testing
        return results

    def run_card(self, orchestration_id: str, card_id: str) -> list[BusResult]:
        """Executa o agente do card (supervisionado), aplica patches e move o card."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None or card.assignee is None:
            raise KeyError(f"Card inválido ou sem agente: {card_id}")
        agent = b.agent_registry.get(card.assignee)
        if agent is None:
            raise KeyError(f"Agente não registrado: {card.assignee}")
        output, events, error = self._execute_isolated(agent, self._build_task(b, card, agent))
        results = self._apply_execution(b, card_id, output, events, error)
        self._persist(b)
        return results

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
            jobs: list[tuple[str, AgentSpec, dict[str, Any]]] = []
            for name in wave:
                card = cards_by_agent.get(name)
                spec = b.agent_registry.get(name)
                if card is not None and spec is not None and card.status == ColumnKey.READY:
                    jobs.append((card.id, spec, self._build_task(b, card, spec)))
            outputs = self._execute_wave([(spec, task) for _cid, spec, task in jobs], concurrent)
            for (card_id, _spec, _task), (output, events, error) in zip(jobs, outputs, strict=True):
                self._apply_execution(b, card_id, output, events, error)
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
        b.gate_engine.register(
            target_phase,
            [
                Criterion(
                    "context_has_output", lambda _c: (b.store.version > 0, "≥1 patch aplicado")
                )
            ],
        )
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
