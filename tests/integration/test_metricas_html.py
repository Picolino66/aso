"""Conteúdo da Tela 29 (Métricas e aprendizado) — wf §31, ADR-0052."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_metricas_nao_e_mais_placeholder() -> None:
    pagina = _client().get("/ui/metricas").text
    assert "active: 'metricas'" in pagina
    assert "FID-25" not in pagina


def test_metricas_tem_filtros_de_projeto_e_periodo() -> None:
    pagina = _client().get("/ui/metricas").text
    for filtro in ["fProjeto", "fDataDe", "fDataAte"]:
        assert filtro in pagina, filtro


def test_metricas_consome_learning_e_recommendations() -> None:
    pagina = _client().get("/ui/metricas").text
    assert "/v1/learning" in pagina
    assert "/v1/learning/recommendations" in pagina


def test_metricas_tem_secao_de_comparacao_de_modelos() -> None:
    pagina = _client().get("/ui/metricas").text
    assert "Comparação de modelos" in pagina
    assert "comparacao" in pagina


def test_demanda_detalhe_linka_para_metricas_agregadas() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/demanda-detalhe?id={oid}").text
    assert "/ui/metricas" in pagina
