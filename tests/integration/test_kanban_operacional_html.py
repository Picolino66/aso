"""Conteúdo de /ui/kanban (Tela 11, wf §13/§35) — ADR-0047."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_kanban_sem_id_mostra_picker() -> None:
    pagina = _client().get("/ui/kanban").text
    assert "listaPicker" in pagina
    assert 'id="app-header"' in pagina
    assert "active: 'kanban'" in pagina


def test_kanban_com_id_consome_endpoint_real() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/kanban?id={oid}").text
    assert "/kanban'" in pagina
    assert "cards/' + encodeURIComponent(cardId) + '/move" in pagina


def test_kanban_tem_drag_and_drop() -> None:
    pagina = _client().get("/ui/kanban").text
    assert "draggable" in pagina
    assert "dragstart" in pagina
    assert "ondrop" in pagina or "'drop'" in pagina


def test_kanban_mostra_erro_de_transicao_invalida() -> None:
    pagina = _client().get("/ui/kanban").text
    assert "erroMove" in pagina


def test_kanban_card_linka_para_detalhe_do_card() -> None:
    pagina = _client().get("/ui/kanban").text
    assert "/ui/card-detalhe?id=" in pagina


def test_demanda_detalhe_aba_cards_linka_para_kanban() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/demanda-detalhe?id={oid}").text
    assert "/ui/kanban?id=" in pagina
