"""API do Dashboard (wf §3.3, Tela 01): /v1/dashboard-summary, /v1/activity — ADR-0037."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_dashboard_summary_devolve_as_6_chaves() -> None:
    client = _client()
    client.post("/v1/orchestrations", json={"user_request": "x"})
    corpo = client.get("/v1/dashboard-summary").json()
    assert set(corpo) == {
        "demandas_ativas",
        "em_execucao",
        "bloqueadas",
        "falhas_abertas",
        "cards_por_status",
        "aprovacoes_por_tipo",
    }
    assert corpo["demandas_ativas"] == 1


def test_dashboard_summary_nao_tem_campo_de_variacao() -> None:
    """Decisão consciente (ADR-0037): sem série temporal real, sem variação
    fabricada."""
    client = _client()
    corpo = client.get("/v1/dashboard-summary").json()
    assert "variacao" not in corpo
    assert not any("variac" in chave for chave in corpo)


def test_activity_devolve_eventos_recentes() -> None:
    client = _client()
    client.post("/v1/orchestrations", json={"user_request": "x"})
    resposta = client.get("/v1/activity")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo
    assert set(corpo[0]) == {"orchestration_id", "tipo", "ator", "at"}


def test_activity_respeita_limite_via_query() -> None:
    client = _client()
    for i in range(5):
        client.post("/v1/orchestrations", json={"user_request": f"demanda {i}"})
    resposta = client.get("/v1/activity?limit=2")
    assert len(resposta.json()) == 2


# ------------------------------------- conteúdo de /ui/dashboard (ADR-0037)


def test_dashboard_html_preserva_contrato_de_header_e_sidebar() -> None:
    client = _client()
    pagina = client.get("/ui/dashboard").text
    assert "/ui/header.js" in pagina
    assert "/ui/sidebar.js" in pagina
    assert 'id="app-header"' in pagina
    assert 'id="app-sidebar"' in pagina
    assert "active: 'dashboard'" in pagina


def test_dashboard_html_consome_os_endpoints_novos() -> None:
    client = _client()
    pagina = client.get("/ui/dashboard").text
    assert "/v1/dashboard-summary" in pagina
    assert "/v1/activity" in pagina


def test_dashboard_html_nao_tem_campo_de_variacao_fabricado() -> None:
    """Decisão consciente (ADR-0037): sem série temporal real, sem variação
    fabricada — os 4 cards de indicador só têm título, valor e link (o
    comentário no JS que EXPLICA a ausência é esperado; o que não pode existir
    é um elemento de UI renderizando uma variação)."""
    client = _client()
    pagina = client.get("/ui/dashboard").text
    assert "valor-variacao" not in pagina
    assert 'class="variacao"' not in pagina
    assert "Variação:" not in pagina


def test_dashboard_html_carrega_mermaid_via_cdn() -> None:
    client = _client()
    pagina = client.get("/ui/dashboard").text
    assert "mermaid" in pagina.lower()
    assert "cdn.jsdelivr.net" in pagina


def test_apenas_dashboard_carrega_mermaid() -> None:
    """Primeira dependência externa do frontend (ADR-0037) — escopada só a esta
    página; as outras 19 continuam sem nenhuma lib externa."""
    client = _client()
    for rota in (
        "/ui/",
        "/ui/nova",
        "/ui/detalhe",
        "/ui/console",
        "/ui/demandas",
        "/ui/esteira",
        "/ui/kanban",
        "/ui/agentes",
        "/ui/modelos",
        "/ui/documentos",
        "/ui/aprovacoes",
        "/ui/execucoes",
        "/ui/testes",
        "/ui/code-reviews",
        "/ui/implantacoes",
        "/ui/incidentes",
        "/ui/auditoria",
        "/ui/metricas",
        "/ui/configuracoes",
    ):
        assert "cdn.jsdelivr.net" not in client.get(rota).text, rota
