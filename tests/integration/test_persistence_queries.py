"""Testes das tabelas de junção e consultas indexadas (§29 normalização estrita)."""

from __future__ import annotations

from pathlib import Path

from aso.control.models import ExecutionPlan, Orchestration
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.governance.models import ADR
from aso.kanban.models import Board, BoardColumn, KanbanCard
from aso.persistence.state import OrchestrationState
from aso.shared.types import (
    CardType,
    ColumnKey,
    ExecutionMode,
    ExecutionStrategy,
    Phase,
    RiskLevel,
)


def _state(oid: str = "orch_q") -> OrchestrationState:
    orch = Orchestration(id=oid, user_request="consulta")
    plan = ExecutionPlan(
        orchestration_id=oid,
        execution_mode=ExecutionMode.FULL_PIPELINE,
        strategy=ExecutionStrategy.SINGLE_AGENT,
        reason="x",
        risk_level=RiskLevel.LOW,
    )
    board = Board(
        id="board_q",
        orchestration_id=oid,
        name="B",
        columns=[BoardColumn(key=ColumnKey.BACKLOG, order=1)],
    )
    c1 = KanbanCard(
        id="c1",
        board_id="board_q",
        orchestration_id=oid,
        phase=Phase.F5,
        type=CardType.TASK,
        title="A",
        status=ColumnKey.DONE,
        linked_adrs=["ADR-0001"],
        acceptance_criteria=["ok"],
    )
    c2 = KanbanCard(
        id="c2",
        board_id="board_q",
        orchestration_id=oid,
        phase=Phase.F5,
        type=CardType.TASK,
        title="B",
        status=ColumnKey.BACKLOG,
    )
    adr = ADR(
        id="ADR-0001",
        orchestration_id=oid,
        title="t",
        phase=Phase.F2,
        tradeoffs=["trade"],
        linked_cards=["c1"],
    )
    return OrchestrationState(
        orchestration=orch, plan=plan, board=board, cards=[c1, c2], adrs=[adr]
    )


def _repo(tmp_path: Path) -> SqlAlchemyOrchestrationRepository:
    repo = SqlAlchemyOrchestrationRepository(f"sqlite:///{tmp_path / 'q.db'}")
    repo.save(_state())
    return repo


def test_cards_by_status_and_count(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert repo.cards_by_status("orch_q", "Done") == ["c1"]
    assert repo.count_cards_by_status("orch_q") == {"Done": 1, "Backlog": 1}


def test_reverse_link_query(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert repo.cards_linked_to_adr("orch_q", "ADR-0001") == ["c1"]


def test_join_tables_roundtrip_preserves_collections(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    state = repo.load("orch_q")
    assert state is not None
    c1 = next(c for c in state.cards if c.id == "c1")
    assert c1.linked_adrs == ["ADR-0001"]
    assert c1.acceptance_criteria == ["ok"]
    assert state.adrs[0].tradeoffs == ["trade"]
    assert state.adrs[0].linked_cards == ["c1"]
    assert state.board.columns[0].key == ColumnKey.BACKLOG


def test_adrs_by_status(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert repo.adrs_by_status("orch_q", "accepted") == []
    assert repo.adrs_by_status("orch_q", "proposed") == ["ADR-0001"]
