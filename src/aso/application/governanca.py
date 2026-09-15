"""`GovernanceOpsService` — patches e conflitos do ledger, auditoria e SLO (ADR-0066).

MEL-32, passo 11d: submissão de patch com aprovação (sempre pelo ContextBus, regra 1),
resolução de conflito, diff de snapshots, auditoria, amostras de SLO, feedback e log de agente
saem da façade.
"""

from __future__ import annotations

import threading
from typing import Any

from aso.application.approvals import _section_delta
from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.governance.contextbus import BusResult
from aso.governance.models import (
    Conflict,
    ContextPatch,
    HumanApproval,
    QualityGateResult,
    SloEvaluation,
)
from aso.kanban.models import KanbanCard
from aso.observability.agent_log import AgentLogBus
from aso.persistence.ports import OrchestrationRepository
from aso.shared.types import AssigneeType, CardType, ColumnKey, ConflictType, PatchStatus


class GovernanceOpsService:
    """Patches e conflitos do ledger (via ContextBus), auditoria, SLO, feedback e log de agente."""

    _RESOLUTIONS = {
        ConflictType.ARCHITECTURE: "Criar ADR de override e referenciá-la em linked_adrs.",
        ConflictType.SNAPSHOT_LOCK: "Criar ADR de override para alterar a seção congelada.",
        ConflictType.CONTRACT: "Criar nova versão de API em vez de alterar/remover o contrato.",
        ConflictType.TOOL_PERMISSION: "Ajustar permissões ou reatribuir o agente.",
    }

    def __init__(
        self,
        store: BundleStore,
        *,
        repository: OrchestrationRepository,
        log_bus: AgentLogBus,
        max_slo_samples: int,
    ) -> None:
        self._bundle_store = store
        self._repo = repository
        self._log_bus = log_bus
        self._max_slo_samples = max_slo_samples

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

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
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            conflict = next((c for c in b.bus.conflicts if c.id == conflict_id), None)
            if conflict is None:
                raise KeyError(f"Conflito inexistente: {conflict_id}")
            self._propose_resolution(b, conflict)
            self._persist(b)
            return conflict

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

    def get_patch(self, orchestration_id: str, patch_id: str) -> ContextPatch | None:
        for patch in self._bundle(orchestration_id).bus.patches:
            if patch.id == patch_id:
                return patch
        return None

    def submit_patch(self, orchestration_id: str, patch: ContextPatch) -> BusResult:
        """Submete um ContextPatch ao ContextBus (§ POST /v1/context-patches)."""
        with self._lock_for(orchestration_id):
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
        with self._lock_for(orchestration_id):
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

    def find_gate_result(self, gate_id: str) -> QualityGateResult | None:
        for oid in self._repo.list_ids():
            for gate in self._bundle(oid).gate_results:
                if gate.id == gate_id:
                    return gate
        return None

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
                    tipo="patch",
                    risk="high",
                    reason="Patch requer aprovação humana antes de aplicar.",
                    payload={"patch_id": patch.id},
                )
            )
            b.event_log.append("ApprovalRequested", {"patch_id": patch.id, "card_id": card_id})
        elif result.status == PatchStatus.REJECTED and result.conflict is not None:
            self._propose_resolution(b, result.conflict, auto=True)
        return result
