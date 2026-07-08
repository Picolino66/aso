"""Round-trip das coleções normalizadas (options_considered, gate criteria, listas planas)."""

from __future__ import annotations

from pathlib import Path

from aso.control.models import ExecutionPlan, Orchestration, PlannedAgent
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.governance.models import (
    ADR,
    Conflict,
    GateCriterionResult,
    QualityGateResult,
    Snapshot,
)
from aso.kanban.models import Board, BoardColumn
from aso.persistence.state import OrchestrationState
from aso.shared.types import (
    ColumnKey,
    ConflictType,
    ExecutionMode,
    ExecutionStrategy,
    GateStatus,
    Phase,
    RiskLevel,
)

OID = "orch_n"


def _state() -> OrchestrationState:
    plan = ExecutionPlan(
        orchestration_id=OID,
        execution_mode=ExecutionMode.FULL_PIPELINE,
        strategy=ExecutionStrategy.SEQUENTIAL,
        reason="r",
        risk_level=RiskLevel.LOW,
        success_criteria=["c1", "c2"],
        agents=[PlannedAgent(agent="A", allowed_tools=["read"], depends_on=["B"])],
    )
    board = Board(
        id="b",
        orchestration_id=OID,
        name="B",
        columns=[BoardColumn(key=ColumnKey.BACKLOG, order=1)],
    )
    adr = ADR(
        id="ADR-0001",
        orchestration_id=OID,
        title="t",
        phase=Phase.F2,
        options_considered=[{"name": "Op1", "pros": ["p1", "p2"], "cons": ["c1"]}],
        tradeoffs=["x"],
    )
    gate = QualityGateResult(
        orchestration_id=OID,
        phase=Phase.F5,
        status=GateStatus.PASSED,
        criteria=[GateCriterionResult(name="k", status=GateStatus.PASSED, evidence=["e"])],
        warnings=["w"],
        required_actions=["a"],
    )
    snap = Snapshot(
        orchestration_id=OID,
        snapshot_version="O5",
        phase=Phase.F5,
        context_hash="h",
        frozen_sections=["engineering"],
        adrs=["ADR-0001"],
        cards=["card1"],
    )
    conflict = Conflict(
        orchestration_id=OID,
        type=ConflictType.CONTRACT,
        description="d",
        source_patch_ids=["p1", "p2"],
    )
    return OrchestrationState(
        orchestration=Orchestration(id=OID, user_request="n"),
        plan=plan,
        board=board,
        adrs=[adr],
        gate_results=[gate],
        snapshots=[snap],
        conflicts=[conflict],
        context_frozen=["architecture"],
    )


def test_normalized_collections_roundtrip(tmp_path: Path) -> None:
    repo = SqlAlchemyOrchestrationRepository(f"sqlite:///{tmp_path / 'n.db'}")
    repo.save(_state())
    st = repo.load(OID)
    assert st is not None

    assert st.plan.success_criteria == ["c1", "c2"]
    assert st.context_frozen == ["architecture"]

    adr = st.adrs[0]
    assert adr.options_considered == [{"name": "Op1", "pros": ["p1", "p2"], "cons": ["c1"]}]
    assert adr.tradeoffs == ["x"]

    gate = st.gate_results[0]
    assert [c.name for c in gate.criteria] == ["k"]
    assert gate.criteria[0].status == GateStatus.PASSED
    assert gate.criteria[0].evidence == ["e"]
    assert gate.warnings == ["w"]
    assert gate.required_actions == ["a"]

    snap = st.snapshots[0]
    assert snap.frozen_sections == ["engineering"]
    assert snap.adrs == ["ADR-0001"]
    assert snap.cards == ["card1"]

    assert st.conflicts[0].source_patch_ids == ["p1", "p2"]
