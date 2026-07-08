"""Testes de autenticação por API key + RBAC (§34)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    auth = AuthService(
        {
            "v": Principal(actor="viewer", role="viewer"),
            "o": Principal(actor="op", role="operator"),
            "a": Principal(actor="adm", role="admin"),
        },
        dev_mode=False,
    )
    return TestClient(create_app(OrchestrationService(), auth=auth))


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_public_endpoints_open() -> None:
    c = _client()
    assert c.get("/health").status_code == 200
    assert c.get("/metrics").status_code == 200
    assert c.get("/").status_code == 200
    assert c.get("/ui/").status_code == 200


def test_requires_valid_token() -> None:
    c = _client()
    assert c.get("/v1/orchestrations").status_code == 401
    assert c.get("/v1/orchestrations", headers=_h("bad")).status_code == 401
    assert c.get("/v1/orchestrations", headers=_h("v")).status_code == 200


def test_rbac_roles() -> None:
    c = _client()
    # viewer lê, mas não cria
    assert (
        c.post("/v1/orchestrations", json={"user_request": "x"}, headers=_h("v")).status_code == 403
    )
    # operator cria
    r = c.post("/v1/orchestrations", json={"user_request": "x"}, headers=_h("o"))
    assert r.status_code == 201
    oid = r.json()["id"]
    ap = c.post(
        f"/v1/orchestrations/{oid}/approvals", json={"action": "deploy"}, headers=_h("o")
    ).json()
    # operator não aprova; admin aprova (e o ator é registrado)
    assert c.post(f"/v1/approvals/{ap['id']}/approve", headers=_h("o")).status_code == 403
    approved = c.post(f"/v1/approvals/{ap['id']}/approve", headers=_h("a")).json()
    assert approved["status"] == "approved"
    assert approved["approved_by"] == "adm"


def test_prometheus_format() -> None:
    c = _client()
    body = c.get("/metrics").text
    assert "aso_orchestrations_total" in body
    assert "# TYPE aso_cards gauge" in body
