"""Testes do SnapshotEngine (TASK-12, §23)."""

from __future__ import annotations

import pytest

from aso.governance.context_store import OrchestratorContextStore
from aso.governance.models import QualityGateResult
from aso.governance.snapshot_engine import SnapshotEngine, SnapshotError
from aso.shared.types import GateStatus, Phase
from tests.unit.conftest import ORCH_ID, make_patch


def _passed_gate() -> QualityGateResult:
    return QualityGateResult(orchestration_id=ORCH_ID, phase=Phase.F2, status=GateStatus.PASSED)


def _failed_gate() -> QualityGateResult:
    return QualityGateResult(orchestration_id=ORCH_ID, phase=Phase.F2, status=GateStatus.FAILED)


def test_create_freezes_sections(store: OrchestratorContextStore) -> None:
    store.apply_patch(make_patch())
    engine = SnapshotEngine()
    snap = engine.create(
        store,
        snapshot_version="O2",
        phase=Phase.F2,
        frozen_sections=["architecture"],
        gate_result=_passed_gate(),
    )
    assert snap.snapshot_version == "O2"
    assert store.is_frozen("architecture.pattern")
    assert snap.context_hash == store.context_hash()


def test_create_requires_passed_gate(store: OrchestratorContextStore) -> None:
    engine = SnapshotEngine()
    with pytest.raises(SnapshotError):
        engine.create(
            store,
            snapshot_version="O2",
            phase=Phase.F2,
            frozen_sections=["architecture"],
            gate_result=_failed_gate(),
        )


def test_restore_reverts_payload(store: OrchestratorContextStore) -> None:
    store.apply_patch(make_patch(content="modular-monolith"))
    engine = SnapshotEngine()
    engine.create(
        store,
        snapshot_version="O2",
        phase=Phase.F2,
        frozen_sections=["architecture"],
        gate_result=_passed_gate(),
    )
    # Altera após o snapshot (fora do fluxo governado, apenas para o teste de restore).
    store._payload["architecture"]["pattern"] = "microservices"  # noqa: SLF001
    engine.restore("O2", store)
    assert store.get_path("architecture.pattern") == "modular-monolith"


def test_restore_does_not_share_references(store: OrchestratorContextStore) -> None:
    store.apply_patch(make_patch(target_path="scope.included", content=["a"]))
    engine = SnapshotEngine()
    snap = engine.create(
        store,
        snapshot_version="O4",
        phase=Phase.F2,
        frozen_sections=["scope"],
        gate_result=_passed_gate(),
    )
    engine.restore("O4", store)
    # Mutar o contexto após o restore não deve corromper o payload do snapshot.
    store.get()  # cópia
    store._payload["scope"]["included"].append("b")  # noqa: SLF001
    assert snap.payload["scope"]["included"] == ["a"]


def test_restore_unknown_snapshot_raises(store: OrchestratorContextStore) -> None:
    engine = SnapshotEngine()
    with pytest.raises(SnapshotError):
        engine.restore("O9", store)
