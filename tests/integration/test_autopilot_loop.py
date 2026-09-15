"""(M4) Loop de autopilot: aprovar um portão de fase avança e roda a próxima sozinho."""

from __future__ import annotations

from aso.application.orchestration_service import OrchestrationService
from aso.control.models import DecisionInput
from aso.shared.types import Phase


def _pending_phase_gate(svc: OrchestrationService, oid: str) -> str | None:
    for a in svc.list_approvals(oid):
        if a.status == "pending" and a.payload.get("kind") == "phase_gate":
            return a.id
    return None


def _multifase(svc: OrchestrationService) -> str:
    """Cards em F2 (arquitetura), F5 (backend) e F6 (revisão); F1, F3, F4 e F7 vazias."""
    return svc.create_orchestration(
        "arquitetura e backend",
        decision_input=DecisionInput(user_request="x", domains=["architecture", "backend"]),
    ).id


def test_start_autopilot_pula_fases_vazias_e_abre_o_primeiro_gate_real() -> None:
    svc = OrchestrationService()
    oid = _multifase(svc)

    result = svc.start_autopilot(oid)
    # F1 vazia: SKIPPED, sem aprovação humana de fase vazia (ADR-0060).
    assert result["fases_puladas"] == ["F1"]
    assert result["phase"] == "F2"
    assert result["gate_status"] == "PASSED"
    assert result["approval_id"]
    # parou no gate real de F2, aguardando aprovação humana
    assert svc.get(oid).current_phase == Phase.F2
    assert [e.payload["phase"] for e in svc.timeline(oid) if e.type == "PhaseSkipped"] == ["F1"]
    assert [s.snapshot_version for s in svc.list_snapshots(oid)] == ["O2"]


def test_approving_phase_gate_auto_advances_and_runs_next() -> None:
    svc = OrchestrationService()
    oid = _multifase(svc)

    first = svc.start_autopilot(oid)
    # aprovar a fase atual → autopilot avança, pula F3/F4 vazias e roda F5 sozinho
    svc.decide_approval(str(first["approval_id"]), approved=True)

    o = svc.get(oid)
    assert o.current_phase == Phase.F5
    # e já abriu a aprovação da PRÓXIMA fase com trabalho (parou ali, aguardando humano)
    assert _pending_phase_gate(svc, oid) is not None


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
