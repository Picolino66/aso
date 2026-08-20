"""API da Tela 02 (Lista de demandas, wf §4) — ADR-0038."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_lista_filtra_por_status_via_query() -> None:
    client = _client()
    client.post("/v1/orchestrations", json={"user_request": "x"})
    resposta = client.get("/v1/orchestrations?status=completed")
    assert resposta.status_code == 200
    assert resposta.json() == []
    assert resposta.headers["X-Total-Count"] == "0"


def test_lista_sem_page_continua_devolvendo_tudo_com_filtro() -> None:
    """Contrato preservado: sem `page`, devolve tudo que bate no filtro (não só
    a primeira página) — o único gatilho de paginação é o parâmetro `page`."""
    client = _client()
    for i in range(3):
        client.post("/v1/orchestrations", json={"user_request": f"bug {i}"})
    resposta = client.get("/v1/orchestrations?q=bug")
    assert len(resposta.json()) == 3
    assert resposta.headers["X-Total-Count"] == "3"


def test_lista_pagina_com_filtro() -> None:
    client = _client()
    for i in range(5):
        client.post("/v1/orchestrations", json={"user_request": f"bug {i}"})
    resposta = client.get("/v1/orchestrations?q=bug&page=1&page_size=2")
    assert len(resposta.json()) == 2
    assert resposta.headers["X-Total-Count"] == "5"


def test_duplicate_endpoint_cria_nova_orquestracao() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda original"}).json()["id"]
    resposta = client.post(f"/v1/orchestrations/{oid}/duplicate")
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["id"] != oid
    assert corpo["user_request"] == "demanda original"


def test_duplicate_endpoint_orquestracao_inexistente_devolve_404() -> None:
    client = _client()
    resposta = client.post("/v1/orchestrations/orch_inexistente/duplicate")
    assert resposta.status_code == 404
