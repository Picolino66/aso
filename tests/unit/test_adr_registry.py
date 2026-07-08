"""Testes do ADRRegistry (§21)."""

from __future__ import annotations

from aso.governance.adr_registry import ADRRegistry
from aso.shared.types import ADRStatus, Phase


def test_sequential_ids() -> None:
    reg = ADRRegistry("orch_test")
    a1 = reg.create(title="Arquitetura", decision="Monolito", phase=Phase.F2)
    a2 = reg.create(title="Stack", decision="Python", phase=Phase.F2)
    assert a1.id == "ADR-0001"
    assert a2.id == "ADR-0002"
    assert a1.status == ADRStatus.ACCEPTED


def test_supersede_marks_old() -> None:
    reg = ADRRegistry("orch_test")
    old = reg.create(title="Stack TS", decision="TypeScript", phase=Phase.F2)
    new = reg.create(title="Stack Python", decision="Python", phase=Phase.F2, supersedes=old.id)
    refreshed = reg.get(old.id)
    assert refreshed is not None
    assert refreshed.status == ADRStatus.SUPERSEDED
    assert refreshed.superseded_by == new.id
    assert new.id not in {a.id for a in reg.accepted() if a.status != ADRStatus.ACCEPTED}


def test_accepted_filter() -> None:
    reg = ADRRegistry("orch_test")
    reg.create(title="A", decision="x", phase=Phase.F2)
    reg.create(title="B", decision="y", phase=Phase.F2, status=ADRStatus.PROPOSED)
    assert len(reg.accepted()) == 1
