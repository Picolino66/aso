"""Testes (b): persistência de ContextPatch + auditoria + submit de patch."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyOrchestrationRepository


def test_patches_recorded_and_persisted(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'a.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    orch = svc.create_orchestration("backend X")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)

    patches = svc.list_patches(orch.id)
    assert len(patches) == 1
    assert patches[0].status.value == "applied"

    # Persistência: nova instância vê o patch.
    svc2 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    reloaded = svc2.list_patches(orch.id)
    assert len(reloaded) == 1
    assert svc2.get_patch(orch.id, reloaded[0].id) is not None
    assert svc2.audit(orch.id)["patches_applied"] == 1


def test_api_audit_and_submit_patch() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "X"}).json()["id"]

    # Submete patch permitido (ArchitectureDesignAgent -> architecture.*) => aplicado.
    ok = client.post(
        f"/v1/orchestrations/{oid}/context-patches",
        json={
            "agent": "ArchitectureDesignAgent",
            "phase": "F2",
            "patch_type": "update",
            "target_path": "architecture.pattern",
            "content": "modular-monolith",
        },
    ).json()
    assert ok["status"] == "applied"

    # Patch sem permissão (agente que não escreve em architecture) => rejeitado.
    denied = client.post(
        f"/v1/orchestrations/{oid}/context-patches",
        json={
            "agent": "DocumentationAgent",
            "phase": "F2",
            "patch_type": "update",
            "target_path": "architecture.pattern",
            "content": "x",
        },
    ).json()
    assert denied["status"] == "rejected"

    patches = client.get(f"/v1/orchestrations/{oid}/patches").json()
    assert len(patches) == 2
    applied = client.get(f"/v1/orchestrations/{oid}/patches?status=applied").json()
    assert len(applied) == 1

    audit = client.get(f"/v1/orchestrations/{oid}/audit").json()
    assert audit["patches_total"] == 2
    assert audit["patches_applied"] == 1
    assert audit["patches_rejected"] == 1
    assert audit["events_total"] >= 1
