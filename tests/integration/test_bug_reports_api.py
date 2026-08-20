"""Registro manual de bug (Tela 21, wf §23, ADR-0049)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _orch(svc: OrchestrationService) -> tuple[str, str]:
    orch = svc.create_orchestration("ajustar tela de checkout")
    card = svc.get_cards(orch.id)[0]
    return orch.id, card.id


def test_criar_bug_manual_cria_card_vinculado() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid, card_id = _orch(svc)

    resposta = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/bug-reports",
        json={
            "titulo": "Login não renova token",
            "cenario": "Token expira e a sessão não renova sozinha",
            "passos_para_reproduzir": ["logar", "esperar expirar", "clicar em qualquer ação"],
            "ambiente": "staging",
            "resultado_atual": "usuário é deslogado",
            "resultado_esperado": "token renova silenciosamente",
            "evidencias": ["print.png"],
            "gravidade": "alta",
            "impacto": "usuários perdem trabalho não salvo",
            "frequencia": "sempre",
            "agente_sugerido": "BackendDevelopmentAgent",
            "retorno_de_fluxo": "retornar_implementacao",
        },
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["card_original_id"] == card_id
    assert corpo["card_id"] != card_id
    assert corpo["titulo"] == "Login não renova token"

    cards = client.get(f"/v1/orchestrations/{oid}/cards").json()
    bug_card = next(c for c in cards if c["id"] == corpo["card_id"])
    assert bug_card["type"] == "Bug"
    assert bug_card["dependencies"] == [card_id]
    assert bug_card["parent_id"] == card_id

    listados = client.get(f"/v1/orchestrations/{oid}/cards/{card_id}/bug-reports").json()
    assert len(listados) == 1
    assert listados[0]["id"] == corpo["id"]

    obtido = client.get(f"/v1/orchestrations/{oid}/bug-reports/{corpo['id']}")
    assert obtido.status_code == 200
    assert obtido.json()["id"] == corpo["id"]


def test_retorno_card_independente_nao_vincula_dependencia() -> None:
    """wf §23.2: das 6 opções de retorno de fluxo, só esta tem efeito real."""
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid, card_id = _orch(svc)

    resposta = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/bug-reports",
        json={"titulo": "Bug independente", "retorno_de_fluxo": "card_independente"},
    )
    assert resposta.status_code == 200
    bug_card_id = resposta.json()["card_id"]

    cards = client.get(f"/v1/orchestrations/{oid}/cards").json()
    bug_card = next(c for c in cards if c["id"] == bug_card_id)
    assert bug_card["dependencies"] == []
    assert bug_card["parent_id"] is None


def test_criar_bug_card_inexistente_devolve_404() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda qualquer"}).json()["id"]
    resposta = client.post(
        f"/v1/orchestrations/{oid}/cards/card-inexistente/bug-reports",
        json={"titulo": "x"},
    )
    assert resposta.status_code == 404


def test_get_bug_report_inexistente_devolve_404() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda qualquer"}).json()["id"]
    resposta = client.get(f"/v1/orchestrations/{oid}/bug-reports/bug-inexistente")
    assert resposta.status_code == 404


def test_list_bug_reports_agregado_da_orquestracao() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid, card_id = _orch(svc)
    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/bug-reports", json={"titulo": "bug 1"})
    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/bug-reports", json={"titulo": "bug 2"})
    todos = client.get(f"/v1/orchestrations/{oid}/bug-reports").json()
    assert len(todos) == 2


def test_diff_stats_sem_branch_e_zerado() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid, card_id = _orch(svc)
    resposta = client.get(f"/v1/orchestrations/{oid}/cards/{card_id}/diff-stats")
    assert resposta.status_code == 200
    assert resposta.json() == {
        "commits": 0,
        "arquivos_alterados": 0,
        "linhas_adicionadas": 0,
        "linhas_removidas": 0,
    }


def test_diff_stats_card_inexistente_devolve_404() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda qualquer"}).json()["id"]
    resposta = client.get(f"/v1/orchestrations/{oid}/cards/card-inexistente/diff-stats")
    assert resposta.status_code == 404
