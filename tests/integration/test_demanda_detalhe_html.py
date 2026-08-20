"""Conteúdo de /ui/demanda-detalhe (wf §6, ADR-0043)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _pagina() -> str:
    client = TestClient(create_app(OrchestrationService()))
    return client.get("/ui/demanda-detalhe").text


def test_demanda_detalhe_preserva_contrato_de_header_e_sidebar() -> None:
    pagina = _pagina()
    assert "/ui/header.js" in pagina
    assert "/ui/sidebar.js" in pagina
    assert 'id="app-header"' in pagina
    assert 'id="app-sidebar"' in pagina
    assert "active: 'demandas'" in pagina


def test_demanda_detalhe_tem_as_treze_abas() -> None:
    pagina = _pagina()
    for aba in [
        "Visão geral",
        "Classificação",
        "Recomendação",
        "Discovery",
        "Documentos",
        "Cards",
        "Execuções",
        "Testes",
        "Reviews",
        "Deploys",
        "Incidentes",
        "Histórico",
        "Métricas",
    ]:
        assert f"'{aba}'" in pagina, f"aba ausente: {aba}"


def test_demanda_detalhe_tem_classificacao_editavel_e_recomendacao() -> None:
    pagina = _pagina()
    assert "/classification" in pagina
    assert "/recommendation" in pagina
    assert "salvarClassificacao" in pagina
    assert "aplicarRecomendacao" in pagina
    assert "ExecutionSettingsUpdated" in pagina


def test_demanda_detalhe_aba_documentos_linka_para_pagina_completa() -> None:
    pagina = _pagina()
    assert "/ui/documentos?id=" in pagina


def test_demanda_detalhe_aba_discovery_tem_painel_log_e_aprovacao() -> None:
    pagina = _pagina()
    assert "rodarDiscovery" in pagina
    assert "/discovery/run" in pagina
    assert "/discovery/approval-criteria" in pagina
    for botao in ["btnAprovar", "btnAprovarObs", "btnReprovar", "btnAjustes"]:
        assert botao in pagina
    assert "Etapas individuais da análise não são rastreáveis hoje" in pagina


def test_demanda_detalhe_tem_progresso_e_responsaveis() -> None:
    pagina = _pagina()
    assert "barraProgresso" in pagina
    assert "responsaveis" in pagina
    assert "agent_assignments" in pagina


def test_demanda_detalhe_mantem_sse_ao_vivo() -> None:
    pagina = _pagina()
    assert "EventSource" in pagina
    assert "/events/stream" in pagina


def test_demanda_detalhe_suporta_aba_inicial_via_query_string() -> None:
    pagina = _pagina()
    assert "ABA_INICIAL" in pagina
    assert "get('aba')" in pagina


def test_demandas_html_aponta_historico_e_documentos_para_demanda_detalhe() -> None:
    client = TestClient(create_app(OrchestrationService()))
    pagina = client.get("/ui/demandas").text
    assert "/ui/demanda-detalhe?id=' + orch.id + '&aba=Histórico'" in pagina
    assert "/ui/demanda-detalhe?id=' + orch.id + '&aba=Documentos'" in pagina
    # "Abrir" continua indo para a sala de controle legada (ação, não navegação de leitura)
    assert "{ rotulo: 'Abrir', href: '/ui/detalhe?id=' + orch.id }" in pagina
