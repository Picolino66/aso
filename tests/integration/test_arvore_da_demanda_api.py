"""API da Tela 10 (Estrutura da demanda, wf §12) — ADR-0040."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_get_cards_tree_devolve_arvore() -> None:
    client = _client()
    oid = client.post(
        "/v1/orchestrations",
        json={
            "user_request": "demanda",
            "execution_mode": "code-execution",
            "validation_command": "pytest -q",
        },
    ).json()["id"]
    epic = client.post(
        f"/v1/orchestrations/{oid}/cards", json={"title": "Autenticação OAuth", "type": "Epic"}
    ).json()
    client.post(
        f"/v1/orchestrations/{oid}/cards",
        json={"title": "Login", "type": "Feature", "parent_id": epic["id"]},
    )
    arvore = client.get(f"/v1/orchestrations/{oid}/cards/tree").json()
    assert len(arvore) >= 1
    raiz = next(n for n in arvore if n["id"] == epic["id"])
    assert raiz["title"] == "Autenticação OAuth"
    assert any(f["title"] == "Login" for f in raiz["filhos"])


def test_create_card_com_parent_inexistente_devolve_409() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    resposta = client.post(
        f"/v1/orchestrations/{oid}/cards", json={"title": "órfão", "parent_id": "card_fantasma"}
    )
    assert resposta.status_code == 409


def test_create_card_orquestracao_inexistente_devolve_404() -> None:
    client = _client()
    resposta = client.post("/v1/orchestrations/orch_inexistente/cards", json={"title": "x"})
    assert resposta.status_code == 404
