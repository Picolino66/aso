"""Teste de integração do fluxo de governança (§41).

Exercita o ciclo do MVP-1: registrar ADR → aplicar ContextPatch via ContextBus →
rodar quality gate → gerar snapshot → validar que a seção congelada fica protegida.
"""

from __future__ import annotations

from aso.governance.adr_registry import ADRRegistry
from aso.governance.context_store import OrchestratorContextStore
from aso.governance.contextbus import ContextBus, PermissionPolicy
from aso.governance.models import ContextPatch
from aso.governance.quality_gate_engine import Criterion, QualityGateEngine
from aso.governance.snapshot_engine import SnapshotEngine
from aso.shared.events import EventLog
from aso.shared.types import GateStatus, PatchStatus, PatchType, Phase

ORCH = "orch_flow"


def test_full_governance_loop_f2() -> None:
    events = EventLog()
    store = OrchestratorContextStore(ORCH)
    registry = ADRRegistry(ORCH)
    permissions = PermissionPolicy({"ArchitectureDesignAgent": ["architecture"]})
    bus = ContextBus(store, permissions=permissions, adr_registry=registry, event_log=events)

    # 1. Registrar ADR da decisão arquitetural.
    adr = registry.create(title="Padrão arquitetural", decision="Modular Monolith", phase=Phase.F2)
    assert adr.id == "ADR-0001"

    # 2. Agente propõe patch; ContextBus valida (7 etapas) e aplica.
    patch = ContextPatch(
        orchestration_id=ORCH,
        agent="ArchitectureDesignAgent",
        phase=Phase.F2,
        patch_type=PatchType.UPDATE,
        target_path="architecture.pattern",
        content="modular-monolith",
    )
    result = bus.submit(patch)
    assert result.status == PatchStatus.APPLIED
    assert store.version == 1

    # 3. Rodar quality gate da fase.
    engine = QualityGateEngine(event_log=events)
    engine.register(
        Phase.F2,
        [Criterion("pattern", lambda c: (bool(c.get("architecture", {}).get("pattern")), "ok"))],
    )
    gate = engine.run(Phase.F2, ORCH, store.get())
    assert gate.status == GateStatus.PASSED

    # 4. Gerar snapshot O2 (congela architecture).
    snap_engine = SnapshotEngine(event_log=events)
    snapshot = snap_engine.create(
        store,
        snapshot_version="O2",
        phase=Phase.F2,
        frozen_sections=["architecture"],
        gate_result=gate,
        adrs=[adr.id],
    )
    assert snapshot.snapshot_version == "O2"
    assert snapshot.context_hash == store.context_hash()

    # 5. Após snapshot, alterar seção congelada sem ADR de override é bloqueado.
    blocked = bus.submit(
        ContextPatch(
            orchestration_id=ORCH,
            agent="ArchitectureDesignAgent",
            phase=Phase.F3,
            patch_type=PatchType.UPDATE,
            target_path="architecture.pattern",
            content="microservices",
        )
    )
    assert blocked.status == PatchStatus.REJECTED
    assert store.get_path("architecture.pattern") == "modular-monolith"

    # 6. Observabilidade: eventos do ciclo registrados.
    types = {e.type for e in events.all()}
    expected = {"ContextPatchApplied", "QualityGateEvaluated", "SnapshotCreated", "ConflictRaised"}
    assert expected <= types
