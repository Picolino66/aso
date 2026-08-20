"""Conteúdo das Telas 18/19/20/21 (code review, correções, testes manuais,
registro de bug) — ADR-0049."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_card_detalhe_review_tem_resumo_e_checklist_de_doze_eixos() -> None:
    pagina = _client().get("/ui/card-detalhe").text
    assert "Resumo" in pagina
    assert "Commits" in pagina
    assert "EIXOS_CODE_REVIEW" in pagina
    assert "Escopo" in pagina
    assert "Cobertura de testes" in pagina
    assert "diff-stats" in pagina


def test_card_detalhe_testes_tem_formulario_de_qa_e_de_bug() -> None:
    pagina = _client().get("/ui/card-detalhe").text
    assert "formQa" in pagina
    assert "formBug" in pagina
    assert "bug-reports" in pagina
    assert "Registrar bug" in pagina


def test_card_detalhe_tem_os_seis_retornos_de_fluxo() -> None:
    pagina = _client().get("/ui/card-detalhe").text
    for retorno in [
        "Retornar para implementação",
        "Retornar para infraestrutura",
        "Retornar para banco de dados",
        "Retornar para documentação",
        "Retornar para arquitetura",
        "Criar card independente",
    ]:
        assert retorno in pagina, retorno


def test_testes_com_id_mostra_plano_manual_e_bugs() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/testes?id={oid}").text
    assert "linhasBugs" in pagina
    assert "/bug-reports'" in pagina


def test_code_reviews_sem_id_mostra_picker() -> None:
    pagina = _client().get("/ui/code-reviews").text
    assert "listaPicker" in pagina
    assert "active: 'code-reviews'" in pagina
    assert "FID-22" not in pagina  # não é mais placeholder


def test_code_reviews_com_id_consome_pulls_reais() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/code-reviews?id={oid}").text
    assert "/pulls'" in pagina
    assert "/ui/card-detalhe?id=" in pagina


def test_demanda_detalhe_linka_para_code_reviews_agregados() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/demanda-detalhe?id={oid}").text
    assert "/ui/code-reviews?id=" in pagina
