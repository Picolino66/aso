"""Contrato HTTP e RBAC do catálogo multi-repo governado."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.control.orchestration_service import OrchestrationService
from aso.shared.types import Phase


def auth() -> AuthService:
    return AuthService(
        {
            "v": Principal(actor="viewer", role="viewer"),
            "o": Principal(actor="operador", role="operator"),
            "a": Principal(actor="administrador", role="admin"),
        },
        dev_mode=False,
    )


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_project(client: TestClient, path: Path, *, name: str = "Projeto") -> dict[str, object]:
    response = client.post(
        "/v1/projects",
        json={"name": name, "description": "descrição", "target_path": str(path)},
        headers=headers("o"),
    )
    assert response.status_code == 201
    return response.json()


def test_rbac_crud_alias_put_e_historico(tmp_path: Path) -> None:
    client = TestClient(create_app(OrchestrationService(), auth=auth()))

    assert client.get("/v1/projects", headers=headers("v")).status_code == 200
    assert (
        client.post(
            "/v1/projects",
            json={"name": "P", "target_path": str(tmp_path)},
            headers=headers("v"),
        ).status_code
        == 403
    )
    project = create_project(client, tmp_path)
    project_id = str(project["id"])

    updated = client.put(
        f"/v1/projects/{project_id}",
        json={"description": "via PUT"},
        headers=headers("o"),
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "via PUT"
    assert client.delete(f"/v1/projects/{project_id}", headers=headers("o")).status_code == 403
    archived = client.delete(f"/v1/projects/{project_id}", headers=headers("a"))
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert client.get("/v1/projects", headers=headers("v")).json() == []
    assert len(client.get("/v1/projects?include_archived=true", headers=headers("v")).json()) == 1
    assert (
        client.post(
            f"/v1/projects/{project_id}/restore",
            json={},
            headers=headers("o"),
        ).status_code
        == 403
    )
    restored = client.post(f"/v1/projects/{project_id}/restore", json={}, headers=headers("a"))
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"
    events = client.get(f"/v1/projects/{project_id}/events", headers=headers("v")).json()
    assert [event["type"] for event in events] == [
        "ProjectCreated",
        "ProjectUpdated",
        "ProjectArchived",
        "ProjectRestored",
    ]
    assert events[-1]["actor"] == "administrador"


def test_erros_de_validacao_not_found_e_conflito(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    client = TestClient(create_app(OrchestrationService(), auth=auth()))

    invalid = client.post(
        "/v1/projects",
        json={"name": "P", "target_path": str(tmp_path / "inexistente")},
        headers=headers("o"),
    )
    assert invalid.status_code == 400
    assert client.get("/v1/projects/ausente", headers=headers("v")).status_code == 404
    project = create_project(client, first, name="Primeiro")
    duplicate = client.post(
        "/v1/projects",
        json={"name": "Duplicado", "target_path": str(first)},
        headers=headers("o"),
    )
    assert duplicate.status_code == 409

    mismatch = client.post(
        "/v1/orchestrations",
        json={
            "user_request": "x",
            "project_id": project["id"],
            "target_path": str(second),
            "execution_mode": "code-execution",
            "validation_command": "true",
        },
        headers=headers("o"),
    )
    assert mismatch.status_code == 409
    assert "diverge" in mismatch.json()["detail"]
    assert (
        client.post(
            "/v1/orchestrations",
            json={
                "user_request": "x",
                "project_id": "inexistente",
                "execution_mode": "code-execution",
                "validation_command": "true",
            },
            headers=headers("o"),
        ).status_code
        == 404
    )
    client.delete(f"/v1/projects/{project['id']}", headers=headers("a"))
    archived = client.post(
        "/v1/orchestrations",
        json={
            "user_request": "x",
            "project_id": project["id"],
            "execution_mode": "code-execution",
            "validation_command": "true",
        },
        headers=headers("o"),
    )
    assert archived.status_code == 409
    assert "arquivado" in archived.json()["detail"]


def test_filtro_snapshot_de_workspace_e_compatibilidade_sem_projeto(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    service = OrchestrationService()
    client = TestClient(create_app(service, auth=auth()))
    project = create_project(client, first)
    project_id = str(project["id"])
    created = client.post(
        "/v1/orchestrations",
        json={
            "user_request": "vinculada",
            "project_id": project_id,
            "execution_mode": "code-execution",
            "validation_command": "true",
        },
        headers=headers("o"),
    )
    assert created.status_code == 201
    orchestration_id = created.json()["id"]
    assert created.json()["target_path"] == str(first.resolve())
    changed = client.patch(
        f"/v1/projects/{project_id}",
        json={"target_path": str(second)},
        headers=headers("o"),
    )
    assert changed.status_code == 200
    assert service.get(orchestration_id).target_path == str(first.resolve())
    filtered = client.get(
        "/v1/orchestrations", params={"project_id": project_id}, headers=headers("v")
    )
    assert [item["id"] for item in filtered.json()] == [orchestration_id]
    loose = client.post("/v1/orchestrations", json={"user_request": "legada"}, headers=headers("o"))
    assert loose.status_code == 201
    assert loose.json()["project_id"] is None
    assert len(client.get("/v1/orchestrations", headers=headers("v")).json()) == 2


def test_arquivamento_preserva_agregado_da_orquestracao(tmp_path: Path) -> None:
    service = OrchestrationService()
    project = service.create_project(
        name="Auditável", description="", target_path=str(tmp_path), actor="op"
    )
    orchestration = service.create_orchestration("preservar tudo", project_id=project.id)
    service.run_quality_gate(orchestration.id, Phase.F1)
    before = {
        "cards": len(service.get_cards(orchestration.id)),
        "adrs": len(service.list_adrs(orchestration.id)),
        "snapshots": len(service.list_snapshots(orchestration.id)),
        "events": len(service.timeline(orchestration.id)),
    }
    client = TestClient(create_app(service, auth=auth()))

    archived = client.delete(f"/v1/projects/{project.id}", headers=headers("a"))

    assert archived.status_code == 200
    assert service.get(orchestration.id).id == orchestration.id
    assert len(service.get_cards(orchestration.id)) == before["cards"]
    assert len(service.list_adrs(orchestration.id)) == before["adrs"]
    assert len(service.list_snapshots(orchestration.id)) == before["snapshots"]
    assert len(service.timeline(orchestration.id)) == before["events"]
    assert (
        client.delete(f"/v1/orchestrations/{orchestration.id}", headers=headers("a")).status_code
        == 405
    )
