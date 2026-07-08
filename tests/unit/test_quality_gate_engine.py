"""Testes do QualityGateEngine (TASK-11, §22)."""

from __future__ import annotations

from typing import Any

import pytest

from aso.governance.quality_gate_engine import Criterion, QualityGateEngine
from aso.shared.types import GateStatus, Phase


def _has_pattern(ctx: dict[str, Any]) -> tuple[bool, str]:
    value = ctx.get("architecture", {}).get("pattern")
    return (bool(value), f"architecture.pattern={value!r}")


def _has_adr(ctx: dict[str, Any]) -> tuple[bool, str]:
    adrs = ctx.get("architecture", {}).get("adrs", [])
    return (len(adrs) >= 1, f"{len(adrs)} ADR(s)")


def test_gate_passes_when_all_criteria_met() -> None:
    engine = QualityGateEngine()
    engine.register(Phase.F2, [Criterion("pattern", _has_pattern), Criterion("adr", _has_adr)])
    ctx = {"architecture": {"pattern": "modular-monolith", "adrs": ["ADR-0001"]}}
    result = engine.run(Phase.F2, "orch_test", ctx)
    assert result.status == GateStatus.PASSED
    assert result.approved_by == "QualityGateEngine"
    assert not result.blocking_issues


def test_gate_fails_and_blocks_when_criterion_missing() -> None:
    engine = QualityGateEngine()
    engine.register(Phase.F2, [Criterion("pattern", _has_pattern), Criterion("adr", _has_adr)])
    ctx = {"architecture": {"pattern": "modular-monolith", "adrs": []}}
    result = engine.run(Phase.F2, "orch_test", ctx)
    assert result.status == GateStatus.FAILED
    assert "adr" in result.blocking_issues
    assert result.approved_by is None


def test_non_blocking_criterion_produces_warning_not_failure() -> None:
    engine = QualityGateEngine()
    engine.register(
        Phase.F2,
        [Criterion("pattern", _has_pattern), Criterion("adr", _has_adr, blocking=False)],
    )
    ctx = {"architecture": {"pattern": "modular-monolith", "adrs": []}}
    result = engine.run(Phase.F2, "orch_test", ctx)
    assert result.status == GateStatus.PASSED
    assert "adr" in result.warnings


def test_unknown_phase_raises() -> None:
    engine = QualityGateEngine()
    with pytest.raises(KeyError):
        engine.run(Phase.F7, "orch_test", {})
