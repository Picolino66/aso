"""Recuperação governada de executor, gate e documentação docs-first."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile


def _service() -> OrchestrationService:
    return OrchestrationService(
        catalog=ExecutorCatalog(
            [
                ExecutorProfile(name="mock", kind="mock", is_default=True),
                ExecutorProfile(
                    name="codex-invalido",
                    kind="cli",
                    command="codex exec",
                    available=False,
                    availability_reason="modelo não anunciado",
                ),
            ]
        )
    )


def test_create_rejeita_executor_indisponivel_sem_persistir(tmp_path: Path) -> None:
    service = _service()
    client = TestClient(create_app(service))
    response = client.post(
        "/v1/orchestrations",
        json={
            "user_request": "x",
            "target_path": str(tmp_path),
            "executor": "codex-invalido",
        },
    )
    assert response.status_code == 409
    assert "modelo não anunciado" in response.json()["detail"]
    assert service.list_all() == []
    assert not (tmp_path / ".git").exists()


def test_create_rejeita_gate_continuo() -> None:
    client = TestClient(create_app(_service()))
    response = client.post(
        "/v1/orchestrations",
        json={
            "user_request": "x",
            "execution_mode": "code-execution",
            "validation_command": "npm run dev",
        },
    )
    assert response.status_code == 400
    assert "contínuo" in response.json()["detail"]


def test_run_card_rejeita_perfil_que_ficou_indisponivel() -> None:
    service = _service()
    orchestration = service.create_orchestration("x")
    bundle = service._bundle(orchestration.id)  # noqa: SLF001
    bundle.orchestration.selected_executor = "codex-invalido"
    service._persist(bundle)  # noqa: SLF001
    card = service.get_cards(orchestration.id)[0]
    client = TestClient(create_app(service))
    response = client.post(f"/v1/orchestrations/{orchestration.id}/cards/{card.id}/run")
    assert response.status_code == 409
    assert any(event.type == "ExecutorRejected" for event in service.timeline(orchestration.id))


def test_patch_execution_settings_persiste_e_audita() -> None:
    service = _service()
    client = TestClient(create_app(service))
    orchestration_id = client.post("/v1/orchestrations", json={"user_request": "x"}).json()["id"]
    response = client.patch(
        f"/v1/orchestrations/{orchestration_id}/execution-settings",
        json={"executor": "mock", "effort": "medium", "validation_command": "npm test"},
    )
    assert response.status_code == 200
    assert response.json()["selected_executor"] == "mock"
    assert response.json()["validation_command"] == "npm test"
    assert any(
        event.type == "ExecutionSettingsUpdated"
        for event in service._bundle(orchestration_id).event_log.all()  # noqa: SLF001
    )


def test_rbac_sync_admin_e_patch_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = AuthService(
        {
            "viewer": Principal(actor="v", role="viewer"),
            "operator": Principal(actor="o", role="operator"),
            "admin": Principal(actor="a", role="admin"),
        },
        dev_mode=False,
    )
    service = _service()
    monkeypatch.setattr(service, "sync_codex_executors", lambda: service.list_executors())
    client = TestClient(create_app(service, auth=auth))
    headers = {"Authorization": "Bearer operator"}
    oid = client.post("/v1/orchestrations", json={"user_request": "x"}, headers=headers).json()[
        "id"
    ]
    assert (
        client.patch(
            f"/v1/orchestrations/{oid}/execution-settings",
            json={"executor": "mock"},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.post("/v1/executors/sync", headers=headers).status_code == 403
    assert (
        client.post("/v1/executors/sync", headers={"Authorization": "Bearer admin"}).status_code
        == 200
    )
