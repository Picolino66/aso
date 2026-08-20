"""Conteúdo de /ui/demanda-estrutura (wf §12, ADR-0040)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _pagina() -> str:
    client = TestClient(create_app(OrchestrationService()))
    return client.get("/ui/demanda-estrutura").text


def test_demanda_estrutura_preserva_contrato_de_header_e_sidebar() -> None:
    pagina = _pagina()
    assert "/ui/header.js" in pagina
    assert "/ui/sidebar.js" in pagina
    assert 'id="app-header"' in pagina
    assert 'id="app-sidebar"' in pagina
    assert "active: 'demandas'" in pagina


def test_demanda_estrutura_consome_endpoints_de_arvore_e_criacao() -> None:
    pagina = _pagina()
    assert "/cards/tree" in pagina
    assert "criarRaiz" in pagina


def test_demanda_estrutura_tem_criacao_por_tipo() -> None:
    pagina = _pagina()
    assert '"Epic"' in pagina
    assert '"Feature"' in pagina
    assert '"Task"' in pagina


def test_demandas_html_aponta_visualizar_cards_para_a_estrutura() -> None:
    client = TestClient(create_app(OrchestrationService()))
    pagina = client.get("/ui/demandas").text
    assert "/ui/demanda-estrutura?id=" in pagina
