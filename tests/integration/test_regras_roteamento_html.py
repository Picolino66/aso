"""Conteúdo de /ui/regras-roteamento (wf §33, ADR-0042)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _pagina() -> str:
    client = TestClient(create_app(OrchestrationService()))
    return client.get("/ui/regras-roteamento").text


def test_regras_roteamento_preserva_contrato_de_header_e_sidebar() -> None:
    pagina = _pagina()
    assert "/ui/header.js" in pagina
    assert "/ui/sidebar.js" in pagina
    assert 'id="app-header"' in pagina
    assert 'id="app-sidebar"' in pagina
    assert "active: 'configuracoes'" in pagina


def test_regras_roteamento_tem_editor_se_entao() -> None:
    pagina = _pagina()
    assert "condicoesEditor" in pagina
    assert "acaoAgente" in pagina
    assert "acaoModelo" in pagina
    assert "acaoEffort" in pagina
    assert "acaoAprovacao" in pagina
    assert "acaoGates" in pagina


def test_regras_roteamento_consome_crud_preview_e_reorder() -> None:
    pagina = _pagina()
    assert "/v1/routing-rules" in pagina
    assert "/v1/routing-rules/preview" in pagina
    assert "/v1/routing-rules/reorder" in pagina


def test_regras_roteamento_gate_de_escrita_por_papel_admin() -> None:
    pagina = _pagina()
    assert "/v1/me" in pagina
    assert "EH_ADMIN" in pagina


def test_console_linka_para_regras_de_roteamento() -> None:
    client = TestClient(create_app(OrchestrationService()))
    pagina = client.get("/ui/console").text
    assert "/ui/regras-roteamento" in pagina
