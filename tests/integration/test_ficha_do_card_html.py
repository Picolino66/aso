"""Conteúdo de /ui/card-detalhe (wf §14, ADR-0041)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _pagina() -> str:
    client = TestClient(create_app(OrchestrationService()))
    return client.get("/ui/card-detalhe").text


def test_card_detalhe_preserva_contrato_de_header_e_sidebar() -> None:
    pagina = _pagina()
    assert "/ui/header.js" in pagina
    assert "/ui/sidebar.js" in pagina
    assert 'id="app-header"' in pagina
    assert 'id="app-sidebar"' in pagina
    assert "active: 'demandas'" in pagina


def test_card_detalhe_tem_as_dez_abas() -> None:
    pagina = _pagina()
    for aba in [
        "Resumo",
        "Plano",
        "Implementação",
        "Arquivos",
        "Testes",
        "Review",
        "Evidências",
        "Dependências",
        "Execuções",
        "Histórico",
    ]:
        assert f"'{aba}'" in pagina, f"aba ausente: {aba}"


def test_card_detalhe_consome_ficha_completa_e_eventos() -> None:
    pagina = _pagina()
    assert "/cards/' + encodeURIComponent(CARD)" in pagina
    assert "/events" in pagina
    assert "/brief" in pagina
    assert "/pulls" in pagina
    assert "/candidate-runs" in pagina


def test_arvore_da_demanda_aponta_no_para_card_detalhe() -> None:
    client = TestClient(create_app(OrchestrationService()))
    pagina = client.get("/ui/demanda-estrutura").text
    assert "/ui/card-detalhe?id=" in pagina
    assert "&card=" in pagina
