"""Teste de integração do OrchestrationService (ciclo MVP-1 §35)."""

from __future__ import annotations

from aso.control.orchestration_service import OrchestrationService
from aso.shared.types import GateStatus, Phase


def test_create_run_gate_snapshot_flow() -> None:
    svc = OrchestrationService()

    # 1-5. Criar orquestração => plano + contexto + board + cards + ADR.
    orch = svc.create_orchestration("Implementar módulo X no backend")
    assert svc.get_plan(orch.id).strategy.value == "single_agent"
    cards = svc.get_cards(orch.id)
    assert len(cards) == 1
    assert len(svc.list_adrs(orch.id)) >= 1  # crit. 10

    # 6-9. Executar agente (mock) => patch aplicado pelo ContextBus.
    results = svc.run_card(orch.id, cards[0].id)
    assert all(r.status.value == "applied" for r in results)
    assert svc.get_context(orch.id)["version"] == 1

    # 11-12. Quality gate + snapshot (card de dev vive em F5).
    gate = svc.run_quality_gate(orch.id, Phase.F5)
    assert gate.status == GateStatus.PASSED
    assert len(svc.list_snapshots(orch.id)) == 1
    assert svc.get(orch.id).snapshot_version == "O5"

    # 13. Timeline registrada.
    event_types = {e.type for e in svc.timeline(orch.id)}
    assert {"OrchestrationCreated", "ContextPatchApplied", "SnapshotCreated"} <= event_types


def test_unknown_orchestration_raises() -> None:
    import pytest

    svc = OrchestrationService()
    with pytest.raises(KeyError):
        svc.get_plan("orch_inexistente")
