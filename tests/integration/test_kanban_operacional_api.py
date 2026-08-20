"""API do Kanban operacional (Tela 11, wf §13/§35) — ADR-0047."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def _seed_card(client: TestClient) -> tuple[str, str]:
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    return oid, card_id


def test_move_valido_e_aceito() -> None:
    client = _client()
    oid, card_id = _seed_card(client)  # card nasce em "Ready"
    resposta = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/move", json={"to_column": "InProgress"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "InProgress"


def test_move_invalido_e_rejeitado_com_motivo() -> None:
    client = _client()
    oid, card_id = _seed_card(client)  # card nasce em "Ready"
    resposta = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/move", json={"to_column": "Done"}
    )
    assert resposta.status_code == 409
    assert "Transição inválida" in resposta.json()["detail"]


def test_move_para_a_mesma_coluna_e_aceito_como_no_op() -> None:
    client = _client()
    oid, card_id = _seed_card(client)
    resposta = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/move", json={"to_column": "Ready"}
    )
    assert resposta.status_code == 200


def test_move_card_inexistente_devolve_404() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    resposta = client.post(
        f"/v1/orchestrations/{oid}/cards/card_fantasma/move", json={"to_column": "Planning"}
    )
    assert resposta.status_code == 404


def test_kanban_board_devolve_16_colunas_com_rotulo_e_transicoes() -> None:
    client = _client()
    oid, card_id = _seed_card(client)
    corpo = client.get(f"/v1/orchestrations/{oid}/kanban").json()
    assert len(corpo["colunas"]) == 16
    por_coluna = {c["coluna"]: c for c in corpo["colunas"]}
    assert por_coluna["Backlog"]["rotulo"] == "Backlog"
    assert por_coluna["Ready"]["rotulo"] == "Pronto para desenvolvimento"
    assert por_coluna["WaitingAgent"]["rotulo"] == "WaitingAgent"  # sem rótulo do wireframe
    assert len(por_coluna["Ready"]["cards"]) == 1
    assert por_coluna["Ready"]["cards"][0]["id"] == card_id
    assert "InProgress" in corpo["transicoes"]["Ready"]


def test_kanban_board_card_tem_os_onze_campos() -> None:
    client = _client()
    oid, card_id = _seed_card(client)
    corpo = client.get(f"/v1/orchestrations/{oid}/kanban").json()
    card = next(c["cards"][0] for c in corpo["colunas"] if c["cards"])
    for campo in [
        "id",
        "titulo",
        "prioridade",
        "agente",
        "modelo",
        "effort",
        "tentativas",
        "falhas",
        "bloqueado",
        "aprovacao_humana_pendente",
        "atualizado_em",
    ]:
        assert campo in card
    assert card["id"] == card_id


def test_kanban_board_marca_bloqueio_e_aprovacao_pendente() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]

    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/block", json={"reason": "dep"})
    svc.request_approval(oid, "merge", reason="risco", card_id=card_id)

    corpo = client.get(f"/v1/orchestrations/{oid}/kanban").json()
    por_coluna = {c["coluna"]: c for c in corpo["colunas"]}
    card = por_coluna["Blocked"]["cards"][0]
    assert card["bloqueado"] is True
    assert card["block_reason"] == "dep"
    assert card["aprovacao_humana_pendente"] is True
