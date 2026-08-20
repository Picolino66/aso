"""Conteúdo de /ui/demanda-nova (wf §5, ADR-0039)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def _pagina(client: TestClient) -> str:
    return client.get("/ui/demanda-nova").text


def test_demanda_nova_preserva_contrato_de_header_e_sidebar() -> None:
    pagina = _pagina(_client())
    assert "/ui/header.js" in pagina
    assert "/ui/sidebar.js" in pagina
    assert 'id="app-header"' in pagina
    assert 'id="app-sidebar"' in pagina
    assert "active: 'demandas'" in pagina


def test_demanda_nova_tem_os_4_blocos_do_wireframe() -> None:
    pagina = _pagina(_client())
    for bloco in ("Informações gerais", "Contexto técnico", "Critérios", "Configuração inicial"):
        assert bloco in pagina, bloco


def test_demanda_nova_tem_campos_dos_4_blocos() -> None:
    pagina = _pagina(_client())
    for campo_id in (
        "titulo",
        "descricao",
        "project_id",
        "solicitante",
        "origem_da_demanda",
        "tipo",
        "resultado_esperado",
        "sistemas_afetados",
        "apis_afetadas",
        "banco_de_dados_afetado",
        "infraestrutura_afetada",
        "dependencias_conhecidas",
        "modulos_afetados",
        "criterios_de_aceite",
        "restricoes",
        "riscos",
        "evidencias_esperadas",
        "risco",
        "complexidade",
        "impactos",
        "aprovacao_humana_obrigatoria",
        "prazo",
        "orcamento_usd",
    ):
        assert f'id="{campo_id}"' in pagina, campo_id


def test_demanda_nova_tem_salvar_rascunho_e_iniciar_como_acoes_distintas() -> None:
    pagina = _pagina(_client())
    assert 'id="salvarRascunho"' in pagina
    assert 'id="iniciar"' in pagina


def test_demandas_html_tem_link_para_nova_demanda() -> None:
    client = _client()
    pagina = client.get("/ui/demandas").text
    assert "/ui/demanda-nova" in pagina
