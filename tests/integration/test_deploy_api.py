"""Implantação governada pela API (§18-22 do fluxo.md, ADR-0023)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.shared.types import Phase, RiskLevel


def _orch_pronta(svc: OrchestrationService, tmp_path: Path, *, risco: RiskLevel) -> str:
    orch = svc.create_orchestration(
        "ajustar cálculo de frete",
        target_path=str(tmp_path),
        seed_cards=False,
        demand_brief=DemandBrief(risco=risco),
    )
    svc.run_quality_gate(orch.id, Phase.F5)  # vacuamente PASSED (sem cards)
    return orch.id


def test_put_config_valida_cada_comando(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    resposta = client.put(
        f"/v1/orchestrations/{oid}/deploy/config", json={"command": "npm run dev"}
    )
    assert resposta.status_code == 400


def test_run_sem_config_devolve_409(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    resposta = client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    assert resposta.status_code == 409


def test_fluxo_completo_risco_baixo_aceita_automatico_e_libera_gate(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    config = client.put(
        f"/v1/orchestrations/{oid}/deploy/config",
        json={"command": "bash -c 'exit 0'", "environment": "homologacao"},
    )
    assert config.status_code == 200

    executado = client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    assert executado.status_code == 200
    corpo = executado.json()
    assert corpo["status"] == "sucesso"
    assert corpo["aceite_status"] == "aprovado"

    gate = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F6"})
    assert gate.status_code == 200
    assert gate.json()["status"] == "PASSED"


def test_fluxo_risco_alto_aguarda_aceite_e_reprova_gate_ate_aprovar(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.HIGH)

    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    executado = client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    assert executado.json()["aceite_status"] == "aguardando_aprovacao"

    gate = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F6"})
    assert gate.status_code == 200
    assert "deploy_aprovado" in gate.json()["blocking_issues"]

    sem_admin = client.post(
        f"/v1/orchestrations/{oid}/deploy/approve",
        json={"approved": True},
        headers={"Authorization": "Bearer viewer-token"},
    )
    # Sem ASO_API_KEYS configurado a API roda em modo dev (sempre admin) —
    # este teste só confirma que a rota EXISTE e aceita a decisão; a garantia
    # de RBAC por sufixo (/approve → admin) já é coberta em test_auth.py.
    assert sem_admin.status_code == 200

    gate_liberado = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F6"})
    assert gate_liberado.json()["status"] == "PASSED"


def test_rollback_cria_card_de_incidente_visivel_na_listagem(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})

    resposta = client.post(
        f"/v1/orchestrations/{oid}/deploy/rollback", json={"reason": "erro grave detectado"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "revertido"

    cards = client.get(f"/v1/orchestrations/{oid}/cards").json()
    incidentes = [c for c in cards if c["type"] == "Incident"]
    assert len(incidentes) == 1
    assert "erro grave detectado" in incidentes[0]["description"]


def test_get_deploy_history_traz_o_ring(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})

    historico = client.get(f"/v1/orchestrations/{oid}/deploy/history").json()
    assert len(historico) == 2
    assert historico[0]["versao"] == 1
    assert historico[1]["versao"] == 2
