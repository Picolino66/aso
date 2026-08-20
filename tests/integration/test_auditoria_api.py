"""Auditoria pela API — cross-demanda, com filtros e export (Tela 28, wf §30,
ADR-0051)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyOrchestrationRepository


def test_audit_vazio_devolve_pagina_vazia() -> None:
    client = TestClient(create_app(OrchestrationService()))
    resposta = client.get("/v1/audit")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo == {"items": [], "total": 0, "page": 1, "page_size": 50}


def test_audit_reflete_movimentacao_manual() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda auditada"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/move", json={"to_column": "InProgress"})

    resposta = client.get("/v1/audit")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] == 1
    item = corpo["items"][0]
    assert item["orchestration_id"] == oid
    assert item["demanda"] == "demanda auditada"
    assert item["model"] is None and item["execution_id"] is None


def test_audit_filtro_por_demanda_e_agente() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid1 = client.post("/v1/orchestrations", json={"user_request": "d1"}).json()["id"]
    oid2 = client.post("/v1/orchestrations", json={"user_request": "d2"}).json()["id"]
    card1 = client.get(f"/v1/orchestrations/{oid1}/cards").json()[0]["id"]
    card2 = client.get(f"/v1/orchestrations/{oid2}/cards").json()[0]["id"]
    client.post(f"/v1/orchestrations/{oid1}/cards/{card1}/move", json={"to_column": "InProgress"})
    client.post(f"/v1/orchestrations/{oid2}/cards/{card2}/move", json={"to_column": "InProgress"})

    todos = client.get("/v1/audit").json()
    assert todos["total"] == 2

    so_d1 = client.get(f"/v1/audit?demanda={oid1}").json()
    assert so_d1["total"] == 1
    assert so_d1["items"][0]["orchestration_id"] == oid1


def test_audit_export_devolve_csv_para_download() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda exportada"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/move", json={"to_column": "InProgress"})

    resposta = client.get("/v1/audit/export")
    assert resposta.status_code == 200
    assert "text/csv" in resposta.headers["content-type"]
    assert "attachment" in resposta.headers["content-disposition"]
    assert "Data e hora" in resposta.text
    assert "demanda exportada" in resposta.text


def test_audit_paginacao_via_api() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    # Card seed nasce em Ready — transições válidas em cadeia (ADR-0047).
    for status in ("InProgress", "Testing", "Review"):
        resposta = client.post(
            f"/v1/orchestrations/{oid}/cards/{card_id}/move", json={"to_column": status}
        )
        assert resposta.status_code == 200

    pagina1 = client.get("/v1/audit?page=1&page_size=2").json()
    assert pagina1["total"] == 3
    assert len(pagina1["items"]) == 2
    pagina2 = client.get("/v1/audit?page=2&page_size=2").json()
    assert len(pagina2["items"]) == 1


def test_audit_via_postgres_like_sqlite_backend(tmp_path: Path) -> None:
    """Confirma que o repositório SQL (não só o in-memory) atende `audit_page` —
    exercitado via SQLite real, mesmo padrão de `test_persistence.py`."""
    url = f"sqlite:///{tmp_path / 'audit.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    client = TestClient(create_app(svc))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda sql"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/move", json={"to_column": "InProgress"})

    resposta = client.get("/v1/audit")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] == 1
    assert corpo["items"][0]["demanda"] == "demanda sql"
    assert corpo["items"][0]["card_titulo"]
