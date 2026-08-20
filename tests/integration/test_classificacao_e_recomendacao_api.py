"""API das Telas 05/13 (classificação editável e recomendação, wf §7/§15) — ADR-0044."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_patch_classification_altera_campos_informados() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]

    resposta = client.patch(
        f"/v1/orchestrations/{oid}/classification",
        json={"tipo": "seguranca", "risco": "high"},
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["tipo"] == "seguranca"
    assert corpo["risco"] == "high"

    brief = client.get(f"/v1/orchestrations/{oid}/brief").json()
    assert brief["tipo"] == "seguranca"


def test_patch_classification_orquestracao_inexistente_devolve_404() -> None:
    client = _client()
    resposta = client.patch("/v1/orchestrations/orch_fantasma/classification", json={"tipo": "x"})
    assert resposta.status_code == 404


def test_get_recommendation_com_regra_casando() -> None:
    client = _client()
    client.post(
        "/v1/routing-rules",
        json={
            "nome": "Segurança crítica",
            "ativa": True,
            "precedencia": 1,
            "condicoes": [{"campo": "tipo", "operador": "igual", "valor": "seguranca"}],
            "acao": {"modelo": "claude-opus-high", "effort": "max", "aprovacao_humana": True},
        },
    )
    oid = client.post(
        "/v1/orchestrations",
        json={"user_request": "corrigir vazamento", "demand_brief": {"tipo": "seguranca"}},
    ).json()["id"]

    resposta = client.get(f"/v1/orchestrations/{oid}/recommendation")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["modelo"] == "claude-opus-high"
    assert corpo["confianca"] == "alta"
    assert corpo["fonte"].startswith("regra:")


def test_get_recommendation_sem_regra_cai_na_heuristica() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "ajuste simples"}).json()["id"]

    resposta = client.get(f"/v1/orchestrations/{oid}/recommendation")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["fonte"] == "heuristica"
    assert corpo["confianca"] == "baixa"
    assert corpo["modelo"] is None


def test_get_recommendation_orquestracao_inexistente_devolve_404() -> None:
    client = _client()
    resposta = client.get("/v1/orchestrations/orch_fantasma/recommendation")
    assert resposta.status_code == 404
