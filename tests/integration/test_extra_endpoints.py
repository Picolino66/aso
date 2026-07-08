"""Testes dos endpoints §28 adicionais (retry, snapshot diff, cards ops) e da UI."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> tuple[TestClient, str, str]:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "X"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    return client, oid, card_id


def test_retry_reexecutes_ready_cards() -> None:
    client, oid, _ = _client()  # card recém-criado está em Ready
    retried = client.post(f"/v1/orchestrations/{oid}/retry").json()["retried"]
    assert len(retried) == 1
    assert client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["status"] == "Testing"


def test_snapshot_diff() -> None:
    client, oid, card_id = _client()
    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")
    client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F5"})
    client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F6"})
    diff = client.get(f"/v1/orchestrations/{oid}/snapshots/O5/diff/O6").json()
    assert diff["from"] == "O5" and diff["to"] == "O6"
    assert client.get(f"/v1/orchestrations/{oid}/snapshots/O5/diff/O9").status_code == 404


def test_card_ops_assign_move_block_unblock() -> None:
    client, oid, card_id = _client()
    assert (
        client.post(
            f"/v1/orchestrations/{oid}/cards/{card_id}/assign-agent",
            json={"agent": "TestingAgent"},
        ).json()["assignee"]
        == "TestingAgent"
    )
    assert (
        client.post(
            f"/v1/orchestrations/{oid}/cards/{card_id}/move", json={"to_column": "Review"}
        ).json()["status"]
        == "Review"
    )
    blocked = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/block", json={"reason": "dep"}
    ).json()
    assert blocked["status"] == "Blocked" and blocked["block_reason"] == "dep"
    assert (
        client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/unblock").json()["status"] == "Ready"
    )


def test_ui_and_root_served() -> None:
    client = TestClient(create_app(OrchestrationService()))
    assert client.get("/").json()["ui"] == "/ui/"
    ui = client.get("/ui/")
    assert ui.status_code == 200
    assert "ASO Runtime" in ui.text
