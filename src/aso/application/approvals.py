"""`ApprovalService` — aprovações humanas, kill-switch e restauração do ledger (ADR-0066).

MEL-32, passo 7: decisão de aprovação (estratégia, patch, fase — regra inviolável 4),
cancelar/retomar e restauração governada do ledger e de seções (ADR-0061).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.control.models import Orchestration
from aso.governance.models import HumanApproval
from aso.persistence.ports import OrchestrationRepository
from aso.shared.types import ColumnKey, PatchStatus


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


class ApprovalService:
    """Decisões humanas (aprovações), kill-switch e restauração governada do ledger."""

    def __init__(
        self,
        store: BundleStore,
        *,
        repository: OrchestrationRepository,
        avancar_apos_gate: Callable[..., Any],
    ) -> None:
        self._bundle_store = store
        self._repo = repository
        self._avancar_apos_gate = avancar_apos_gate

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    def _advance_after_phase_gate(self, *args: Any, **kwargs: Any) -> Any:
        return self._avancar_apos_gate(*args, **kwargs)

    def request_approval(
        self,
        orchestration_id: str,
        action: str,
        *,
        risk: str = "medium",
        reason: str = "",
        card_id: str | None = None,
    ) -> HumanApproval:
        with self._lock_for(orchestration_id):
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

    def request_card_help(
        self, orchestration_id: str, card_id: str, *, reason: str = ""
    ) -> HumanApproval:
        """Solicitar ajuda (Tela 15, wf §17.2) — reaproveita `request_approval`
        (genérico, já aceita `card_id`), com a ação rotulada explicitamente."""
        return self.request_approval(
            orchestration_id, "solicitar_ajuda", reason=reason, card_id=card_id
        )

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
            # Estratégia rejeitada (regra 4): a orquestração não pode seguir executando o
            # plano que o humano negou — cancela (kill-switch) e registra a causa.
            if not approved and approval.tipo == "estrategia":
                bundle.orchestration.status = "cancelled"
                bundle.event_log.append(
                    "StrategyRejected", {"approval_id": approval_id, "by": approved_by}
                )
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
                agendar=True,
            )
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
        """Alias de `restaurar_ledger` mantido por uma versão (ADR-0061)."""
        return self.restaurar_ledger(orchestration_id, to_snapshot)

    def restaurar_ledger(self, orchestration_id: str, to_snapshot: str) -> Orchestration:
        """Restaura o LEDGER do contexto (payload + seções congeladas) a um snapshot.

        Não reverte código, branches, board, aprovações nem implantações — só o
        `OrchestratorContext`. O nome antigo (`rollback`) sugeria desfazer tudo (ADR-0061).
        Bypass governado do ContextBus: exige admin na API e registra ADR.
        """
        with self._lock_for(orchestration_id):
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
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            b.orchestration.status = "cancelled"
            b.event_log.append("OrchestrationCancelled", {"orchestration_id": orchestration_id})
            self._persist(b)
            return b.orchestration

    def resume(self, orchestration_id: str) -> Orchestration:
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            b.orchestration.status = "running"
            b.event_log.append("OrchestrationResumed", {"orchestration_id": orchestration_id})
            self._persist(b)
            return b.orchestration

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
