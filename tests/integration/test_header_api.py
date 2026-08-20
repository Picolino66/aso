"""API do header (wf §2.3): /v1/me, /v1/header-summary, /v1/search, filtros de
/v1/approvals — ADR-0035."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_me_devolve_actor_e_role_do_principal_autenticado() -> None:
    client = _client()
    corpo = client.get("/v1/me").json()
    assert corpo["actor"]
    assert corpo["role"] in {"viewer", "operator", "admin"}


def test_header_summary_global() -> None:
    client = _client()
    client.post("/v1/orchestrations", json={"user_request": "x"})
    resposta = client.get("/v1/header-summary")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert set(corpo) == {"execucoes_ativas", "falhas", "aprovacoes_pendentes"}


def test_header_summary_escopado_por_projeto(tmp_path: Path) -> None:
    client = _client()
    projeto = client.post(
        "/v1/projects", json={"name": "P", "description": "", "target_path": str(tmp_path)}
    ).json()
    client.post("/v1/orchestrations", json={"user_request": "dentro", "project_id": projeto["id"]})
    resposta = client.get(f"/v1/header-summary?project_id={projeto['id']}")
    assert resposta.status_code == 200


def test_search_endpoint_encontra_demanda() -> None:
    client = _client()
    client.post("/v1/orchestrations", json={"user_request": "implementar cálculo de frete"})
    resultados = client.get("/v1/search?q=frete").json()
    assert any(r["tipo"] == "demanda" for r in resultados)


def test_search_endpoint_sem_query_devolve_vazio() -> None:
    client = _client()
    client.post("/v1/orchestrations", json={"user_request": "x"})
    assert client.get("/v1/search").json() == []


def test_approvals_filtra_por_status() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "x"}).json()["id"]
    client.post(
        f"/v1/orchestrations/{oid}/approvals",
        json={"action": "deploy", "risk": "high", "reason": "r"},
    )
    pendentes = client.get("/v1/approvals?status=pending").json()
    assert len(pendentes) == 1
    aprovadas = client.get("/v1/approvals?status=approved").json()
    assert aprovadas == []


def test_approvals_filtra_por_projeto(tmp_path: Path) -> None:
    client = _client()
    projeto = client.post(
        "/v1/projects", json={"name": "P2", "description": "", "target_path": str(tmp_path)}
    ).json()
    oid_dentro = client.post(
        "/v1/orchestrations", json={"user_request": "dentro", "project_id": projeto["id"]}
    ).json()["id"]
    client.post("/v1/orchestrations", json={"user_request": "fora"})
    client.post(
        f"/v1/orchestrations/{oid_dentro}/approvals",
        json={"action": "deploy", "risk": "high", "reason": "r"},
    )
    resultado = client.get(f"/v1/approvals?project_id={projeto['id']}").json()
    assert len(resultado) == 1
    assert resultado[0]["orchestration_id"] == oid_dentro
