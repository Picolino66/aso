"""MEL-10 — avanço de fase exige gate aprovado (regra inviolável 3) e papel admin.

Os testes tentam explicitamente burlar a regra: avançar sem gate, com gate reprovado e
com um PASSED antigo mascarado por um FAILED mais recente.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.application.orchestration_service import OrchestrationService
from aso.control.models import DecisionInput
from aso.governance.models import QualityGateResult
from aso.shared.types import GateStatus, Phase


def _registrar_gate(svc: OrchestrationService, oid: str, status: GateStatus) -> None:
    """Injeta um resultado de gate da fase atual (o gate real só reprova com cards)."""
    b = svc._bundle(oid)  # noqa: SLF001 - o histórico de gates é o objeto do teste
    b.gate_results.append(
        QualityGateResult(orchestration_id=oid, phase=b.orchestration.current_phase, status=status)
    )


def _recusas(svc: OrchestrationService, oid: str) -> list[dict[str, object]]:
    return [e.payload for e in svc.timeline(oid) if e.type == "PhaseAdvanceRefused"]


def test_sem_gate_executado_o_avanco_e_recusado() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    with pytest.raises(ValueError, match="gate de F1 nunca executado"):
        svc.advance_phase(orch.id)
    assert svc.get(orch.id).current_phase == Phase.F1
    assert _recusas(svc, orch.id) == [{"phase": "F1", "reason": "gate de F1 nunca executado"}]


def test_gate_reprovado_recusa_o_avanco() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    _registrar_gate(svc, orch.id, GateStatus.FAILED)
    with pytest.raises(ValueError, match="não aprovado: FAILED"):
        svc.advance_phase(orch.id)
    assert svc.get(orch.id).current_phase == Phase.F1


def test_passed_antigo_seguido_de_failed_nao_libera() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    _registrar_gate(svc, orch.id, GateStatus.PASSED)
    _registrar_gate(svc, orch.id, GateStatus.FAILED)
    with pytest.raises(ValueError, match="não aprovado"):
        svc.advance_phase(orch.id)
    assert svc.get(orch.id).current_phase == Phase.F1


def test_gate_aprovado_de_outra_fase_nao_libera_a_atual() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    svc.run_quality_gate(orch.id)
    svc.advance_phase(orch.id)  # F1 → F2 com gate de F1 aprovado
    # O PASSED de F1 continua no histórico, mas não vale para F2.
    with pytest.raises(ValueError, match="gate de F2 nunca executado"):
        svc.advance_phase(orch.id)
    assert svc.get(orch.id).current_phase == Phase.F2


def test_ultimo_gate_liberado_avanca() -> None:
    # F1 sem cards: o gate mais recente é SKIPPED, que libera como PASSED (ADR-0060).
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    _registrar_gate(svc, orch.id, GateStatus.FAILED)
    assert svc.run_quality_gate(orch.id).status == GateStatus.SKIPPED
    assert svc.advance_phase(orch.id).current_phase == Phase.F2
    assert _recusas(svc, orch.id) == []


def test_skipped_antigo_seguido_de_failed_nao_libera() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    _registrar_gate(svc, orch.id, GateStatus.SKIPPED)
    _registrar_gate(svc, orch.id, GateStatus.FAILED)
    with pytest.raises(ValueError, match="não aprovado"):
        svc.advance_phase(orch.id)


def _em_f2_com_card() -> tuple[OrchestrationService, str]:
    """Orquestração com cards em F2 e F5, já avançada até F2 (F1 vazia = SKIPPED)."""
    svc = OrchestrationService()
    oid = svc.create_orchestration(
        "arquitetura e backend",
        decision_input=DecisionInput(user_request="x", domains=["architecture", "backend"]),
    ).id
    svc.run_quality_gate(oid)
    svc.advance_phase(oid)
    return svc, oid


def test_autopilot_continua_avancando_apos_aprovar_fase_gate() -> None:
    svc, oid = _em_f2_com_card()
    resultado = svc.run_phase(oid)
    assert resultado["gate_status"] == "PASSED"
    svc.decide_approval(str(resultado["approval_id"]), approved=True)
    # F3 e F4 vazias são puladas sem aprovação; o autopilot para no gate real de F5.
    assert svc.get(oid).current_phase == Phase.F5
    assert [e.payload["phase"] for e in svc.timeline(oid) if e.type == "PhaseSkipped"] == [
        "F3",
        "F4",
    ]


def test_autopilot_nao_arrasta_fase_com_gate_reprovado_depois_da_aprovacao() -> None:
    svc, oid = _em_f2_com_card()
    resultado = svc.run_phase(oid)
    # Um gate reprovado rodado depois da abertura da aprovação invalida o avanço.
    _registrar_gate(svc, oid, GateStatus.FAILED)
    aprovacao = svc.decide_approval(str(resultado["approval_id"]), approved=True)
    assert aprovacao.status == "approved"
    assert svc.get(oid).current_phase == Phase.F2
    assert len(_recusas(svc, oid)) == 1


def _client_rbac() -> tuple[TestClient, OrchestrationService]:
    auth = AuthService(
        {
            "o": Principal(actor="op", role="operator"),
            "a": Principal(actor="adm", role="admin"),
        },
        dev_mode=False,
    )
    svc = OrchestrationService()
    return TestClient(create_app(svc, auth=auth)), svc


def test_rota_recusa_operator_com_403_e_sem_gate_com_409() -> None:
    client, svc = _client_rbac()
    op = {"Authorization": "Bearer o"}
    adm = {"Authorization": "Bearer a"}
    oid = client.post("/v1/orchestrations", json={"user_request": "x"}, headers=op).json()["id"]

    assert client.post(f"/v1/orchestrations/{oid}/advance-phase", headers=op).status_code == 403
    sem_gate = client.post(f"/v1/orchestrations/{oid}/advance-phase", headers=adm)
    assert sem_gate.status_code == 409
    assert "nunca executado" in sem_gate.json()["detail"]
    assert svc.get(oid).current_phase == Phase.F1

    gate = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={}, headers=op)
    assert gate.status_code == 200
    # Mesmo com gate aprovado, operator continua sem poder avançar.
    assert client.post(f"/v1/orchestrations/{oid}/advance-phase", headers=op).status_code == 403
    ok = client.post(f"/v1/orchestrations/{oid}/advance-phase", headers=adm)
    assert ok.status_code == 200
    assert ok.json()["current_phase"] == "F2"
