"""SnapshotEngine (§23).

Gera snapshots imutáveis após um quality gate aprovado, congela as seções do
contexto correspondentes e permite restaurar um estado anterior.
"""

from __future__ import annotations

from aso.governance.context_store import OrchestratorContextStore
from aso.governance.models import QualityGateResult, Snapshot
from aso.shared.events import EventLog
from aso.shared.types import GateStatus, Phase


class SnapshotError(RuntimeError):
    """Erro ao criar ou restaurar snapshot."""


class SnapshotEngine:
    """Cria, lista e restaura snapshots de uma orquestração."""

    def __init__(self, event_log: EventLog | None = None) -> None:
        self._snapshots: dict[str, Snapshot] = {}
        self.event_log = event_log or EventLog()

    def create(
        self,
        store: OrchestratorContextStore,
        *,
        snapshot_version: str,
        phase: Phase,
        frozen_sections: list[str],
        gate_result: QualityGateResult,
        adrs: list[str] | None = None,
        cards: list[str] | None = None,
    ) -> Snapshot:
        """Cria um snapshot exigindo que o gate da fase tenha passado."""
        if gate_result.status != GateStatus.PASSED:
            raise SnapshotError(
                f"Não é possível criar snapshot {snapshot_version}: "
                f"gate da fase {phase.value} não está PASSED."
            )

        snapshot = Snapshot(
            orchestration_id=store.orchestration_id,
            snapshot_version=snapshot_version,
            phase=phase,
            context_hash=store.context_hash(),
            frozen_sections=list(frozen_sections),
            quality_gate_result_id=gate_result.id,
            adrs=list(adrs or []),
            cards=list(cards or []),
            payload=store.get(),
        )
        store.freeze(frozen_sections)
        self._snapshots[snapshot_version] = snapshot
        self.event_log.append(
            "SnapshotCreated",
            {"snapshot_version": snapshot_version, "phase": phase.value, "frozen": frozen_sections},
        )
        return snapshot

    def hydrate(self, snapshots: list[Snapshot]) -> None:
        """Reidrata o engine a partir de snapshots persistidos."""
        self._snapshots = {s.snapshot_version: s for s in snapshots}

    def get(self, snapshot_version: str) -> Snapshot | None:
        return self._snapshots.get(snapshot_version)

    def list_all(self) -> list[Snapshot]:
        return sorted(self._snapshots.values(), key=lambda s: s.snapshot_version)

    def restore(self, snapshot_version: str, store: OrchestratorContextStore) -> None:
        """Restaura o contexto para o estado de um snapshot (protocolo de rollback)."""
        snapshot = self._snapshots.get(snapshot_version)
        if snapshot is None:
            raise SnapshotError(f"Snapshot {snapshot_version} inexistente.")
        # Restaura payload (deep copy) e re-congela as seções do snapshot.
        store.restore_from(snapshot.payload, snapshot.frozen_sections)
        self.event_log.append("SnapshotRestored", {"snapshot_version": snapshot_version})
