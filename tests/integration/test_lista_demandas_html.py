"""Conteúdo de /ui/demandas (wf §4, ADR-0038)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _pagina() -> str:
    client = TestClient(create_app(OrchestrationService()))
    return client.get("/ui/demandas").text


def test_demandas_html_preserva_contrato_de_header_e_sidebar() -> None:
    pagina = _pagina()
    assert "/ui/header.js" in pagina
    assert "/ui/sidebar.js" in pagina
    assert 'id="app-header"' in pagina
    assert 'id="app-sidebar"' in pagina
    assert "active: 'demandas'" in pagina


def test_demandas_html_tem_os_11_controles_de_filtro() -> None:
    pagina = _pagina()
    for campo in (
        "f-q",
        "f-project_id",
        "f-tipo",
        "f-risco",
        "f-complexidade",
        "f-impacto",
        "f-status",
        "f-executor",
        "f-created_from",
        "f-created_to",
        "f-aprovacao_humana",
    ):
        assert f'id="{campo}"' in pagina, campo


def test_demandas_html_tem_as_11_acoes_nomeadas() -> None:
    pagina = _pagina()
    for acao in (
        "Abrir",
        "Editar",
        "Duplicar",
        "Priorizar",
        "Bloquear",
        "Cancelar",
        "Visualizar histórico",
        "Visualizar documentos",
        "Visualizar cards",
        "Reiniciar etapa",
        "Solicitar intervenção humana",
    ):
        assert acao in pagina, acao


def test_demandas_html_consome_endpoint_de_listagem_e_duplicar() -> None:
    pagina = _pagina()
    assert "/v1/orchestrations?" in pagina
    assert "/duplicate" in pagina
