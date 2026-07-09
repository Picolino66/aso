"""(M4) Loop de autopilot: aprovar um portão de fase avança e roda a próxima sozinho."""

from __future__ import annotations

from aso.control.orchestration_service import OrchestrationService
from aso.shared.types import Phase


def _pending_phase_gate(svc: OrchestrationService, oid: str) -> str | None:
    for a in svc.list_approvals(oid):
        if a.status == "pending" and a.payload.get("kind") == "phase_gate":
            return a.id
    return None


def test_start_autopilot_opens_first_phase_gate() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    start_phase = orch.current_phase

    result = svc.start_autopilot(orch.id)
    assert result["gate_status"] == "PASSED"
    assert result["approval_id"]
    # a fase ainda não avançou (aguarda aprovação humana)
    assert svc.get(orch.id).current_phase == start_phase


def test_approving_phase_gate_auto_advances_and_runs_next() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    start = orch.current_phase

    first = svc.start_autopilot(orch.id)
    # aprovar a fase atual → autopilot avança e roda a próxima automaticamente
    svc.decide_approval(first["approval_id"], approved=True)

    o = svc.get(orch.id)
    assert o.current_phase == OrchestrationService._next_phase(start)  # avançou sozinho
    # e já abriu a aprovação da PRÓXIMA fase (parou ali, aguardando humano)
    assert _pending_phase_gate(svc, orch.id) is not None


def test_autopilot_chains_to_completion() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    svc.start_autopilot(orch.id)

    # aprova cada portão de fase até a esteira concluir (pausa só na aprovação)
    for _ in range(len(list(Phase)) + 1):
        ap = _pending_phase_gate(svc, orch.id)
        if ap is None:
            break
        svc.decide_approval(ap, approved=True)

    o = svc.get(orch.id)
    assert o.current_phase == Phase.F7
    assert o.status == "completed"
    assert _pending_phase_gate(svc, orch.id) is None  # nada mais pendente


def test_autopilot_endpoint() -> None:
    from fastapi.testclient import TestClient

    from aso.api.app import create_app

    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = client.post("/v1/orchestrations", json={"user_request": "X"}).json()["id"]
    res = client.post(f"/v1/orchestrations/{oid}/autopilot")
    assert res.status_code == 200
    assert res.json()["approval_id"]
