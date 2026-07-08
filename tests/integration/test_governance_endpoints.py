"""Testes (b): persistência de gates/approvals + endpoints §28 restantes."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.models import DecisionInput
from aso.control.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyOrchestrationRepository


def test_gates_and_approvals_persist(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'g.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    orch = svc.create_orchestration(
        "deploy em produção",
        decision_input=DecisionInput(user_request="deploy", domains=["devops"], impacts=["deploy"]),
    )
    # Ação crítica (impacto deploy) => aprovação humana criada automaticamente.
    assert len(svc.list_approvals(orch.id)) == 1

    for card in svc.get_cards(orch.id):
        svc.run_card(orch.id, card.id)
    svc.run_quality_gate(orch.id)
    assert len(svc.list_gate_results(orch.id)) == 1

    # Nova instância sobre o mesmo banco: gates e approvals persistidos.
    svc2 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    assert len(svc2.list_gate_results(orch.id)) == 1
    approval = svc2.list_approvals(orch.id)[0]
    decided = svc2.decide_approval(approval.id, approved=True)
    assert decided.status == "approved"
    # persistência da decisão
    svc3 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    assert svc3.get_approval(approval.id).status == "approved"  # type: ignore[union-attr]


def _client_ready() -> tuple[TestClient, str]:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "X"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")
    client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={})
    return client, oid


def test_quality_gate_and_conflict_endpoints() -> None:
    client, oid = _client_ready()
    gates = client.get(f"/v1/orchestrations/{oid}/quality-gates").json()
    assert len(gates) == 1
    gid = gates[0]["id"]
    assert client.get(f"/v1/quality-gates/{gid}").json()["status"] == "PASSED"
    assert client.get("/v1/quality-gates/nope").status_code == 404
    assert client.get(f"/v1/orchestrations/{oid}/conflicts").json() == []


def test_approval_endpoints() -> None:
    client, oid = _client_ready()
    created = client.post(
        f"/v1/orchestrations/{oid}/approvals", json={"action": "deploy", "risk": "high"}
    ).json()
    aid = created["id"]
    assert any(a["id"] == aid for a in client.get("/v1/approvals").json())
    assert client.get(f"/v1/approvals/{aid}").json()["status"] == "pending"
    assert client.post(f"/v1/approvals/{aid}/approve").json()["status"] == "approved"
    assert client.post("/v1/approvals/xxx/reject").status_code == 404


def test_lifecycle_endpoints() -> None:
    client, oid = _client_ready()
    rb = client.post(f"/v1/orchestrations/{oid}/rollback", json={"to_snapshot": "O5"})
    assert rb.status_code == 202
    assert rb.json()["snapshot_version"] == "O5"
    assert (
        client.post(f"/v1/orchestrations/{oid}/rollback", json={"to_snapshot": "O9"}).status_code
        == 404
    )
    assert client.post(f"/v1/orchestrations/{oid}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/v1/orchestrations/{oid}/resume").json()["status"] == "running"
