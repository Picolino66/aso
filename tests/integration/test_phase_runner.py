"""(M3) PhaseRunner: executa uma fase, roda o gate e abre a aprovação de avanço."""

from __future__ import annotations

import pytest

from aso.control.orchestration_service import OrchestrationService
from aso.shared.types import Phase


def test_run_phase_executes_gate_and_opens_approval() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend API")
    phase = orch.current_phase

    result = svc.run_phase(orch.id)
    assert result["phase"] == phase.value
    assert result["gate_status"] == "PASSED"
    assert result["snapshot"]  # snapshot da fase gerado
    assert result["approval_id"]  # aprovação de avanço aberta
    assert result["next_phase"]  # há próxima fase

    # a aprovação existe, está pendente e é do tipo phase_gate
    approvals = svc.list_approvals(orch.id)
    ap = next(a for a in approvals if a.id == result["approval_id"])
    assert ap.status == "pending"
    assert ap.payload["kind"] == "phase_gate"
    assert ap.payload["phase"] == phase.value


def test_advance_phase_moves_to_next_and_blocks_at_end() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    start = orch.current_phase
    updated = svc.advance_phase(orch.id)
    assert updated.current_phase == OrchestrationService._next_phase(start)

    # empurra até F7 e confirma o bloqueio na última fase
    while OrchestrationService._next_phase(svc.get(orch.id).current_phase) is not None:
        svc.advance_phase(orch.id)
    assert svc.get(orch.id).current_phase == Phase.F7
    with pytest.raises(ValueError, match="última fase"):
        svc.advance_phase(orch.id)


def test_run_phase_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from aso.api.app import create_app

    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = client.post("/v1/orchestrations", json={"user_request": "X"}).json()["id"]

    res = client.post(f"/v1/orchestrations/{oid}/run-phase", json={})
    assert res.status_code == 200
    assert res.json()["gate_status"] == "PASSED"

    adv = client.post(f"/v1/orchestrations/{oid}/advance-phase")
    assert adv.status_code == 200
