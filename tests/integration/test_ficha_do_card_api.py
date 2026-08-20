"""API da Tela 12 (Detalhes do card, wf §14) — ADR-0041."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_get_card_devolve_ficha_completa() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    card = client.post(f"/v1/orchestrations/{oid}/cards", json={"title": "Login OAuth"}).json()

    resposta = client.get(f"/v1/orchestrations/{oid}/cards/{card['id']}")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["id"] == card["id"]
    assert corpo["title"] == "Login OAuth"
    assert "dependencies" in corpo
    assert "qa_checks" in corpo


def test_get_card_inexistente_devolve_404() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    resposta = client.get(f"/v1/orchestrations/{oid}/cards/card_fantasma")
    assert resposta.status_code == 404


def test_get_card_events_devolve_lista_vazia_para_card_novo() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    card = client.post(f"/v1/orchestrations/{oid}/cards", json={"title": "Login OAuth"}).json()

    resposta = client.get(f"/v1/orchestrations/{oid}/cards/{card['id']}/events")

    assert resposta.status_code == 200
    assert resposta.json() == []


def test_get_card_events_reflete_movimentacoes() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    card = client.post(f"/v1/orchestrations/{oid}/cards", json={"title": "Login OAuth"}).json()

    # "Planning" é a única transição manual válida a partir de "Backlog" (wf §35,
    # ADR-0047) — este teste cobre o registro do evento, não a máquina de estados.
    mover = client.post(
        f"/v1/orchestrations/{oid}/cards/{card['id']}/move", json={"to_column": "Planning"}
    )
    assert mover.status_code == 200

    eventos = client.get(f"/v1/orchestrations/{oid}/cards/{card['id']}/events").json()
    assert len(eventos) == 1
    assert eventos[0]["to_status"] == "Planning"
    assert eventos[0]["card_id"] == card["id"]


def test_get_card_events_inexistente_devolve_404() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    resposta = client.get(f"/v1/orchestrations/{oid}/cards/card_fantasma/events")
    assert resposta.status_code == 404


def test_rotas_literais_de_cards_nao_sao_sombreadas() -> None:
    """`cards/tree`, `cards/stats` e `cards/by-status/{status}` continuam
    respondendo pelo próprio handler, não pelo novo `GET cards/{card_id}`."""
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]

    assert client.get(f"/v1/orchestrations/{oid}/cards/tree").status_code == 200
    assert client.get(f"/v1/orchestrations/{oid}/cards/stats").status_code == 200
    assert client.get(f"/v1/orchestrations/{oid}/cards/by-status/Backlog").status_code == 200
