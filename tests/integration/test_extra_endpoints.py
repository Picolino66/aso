"""Testes dos endpoints §28 adicionais (retry, snapshot diff, cards ops) e da UI."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> tuple[TestClient, str, str]:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "X"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    return client, oid, card_id


def test_retry_reexecutes_ready_cards() -> None:
    client, oid, _ = _client()  # card recém-criado está em Ready
    retried = client.post(f"/v1/orchestrations/{oid}/retry").json()["retried"]
    assert len(retried) == 1
    assert client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["status"] == "Testing"


def test_snapshot_diff() -> None:
    client, oid, card_id = _client()
    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")
    client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F5"})
    client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F6"})
    diff = client.get(f"/v1/orchestrations/{oid}/snapshots/O5/diff/O6").json()
    assert diff["from"] == "O5" and diff["to"] == "O6"
    assert client.get(f"/v1/orchestrations/{oid}/snapshots/O5/diff/O9").status_code == 404


def test_card_ops_assign_move_block_unblock() -> None:
    client, oid, card_id = _client()
    assert (
        client.post(
            f"/v1/orchestrations/{oid}/cards/{card_id}/assign-agent",
            json={"agent": "TestingAgent"},
        ).json()["assignee"]
        == "TestingAgent"
    )
    # O card recém-criado nasce em "Ready" — "InProgress" é a única transição
    # manual válida a partir dali (wf §35, ADR-0047); este teste cobre a cadeia
    # assign→move→block→unblock, não a máquina de estados em si.
    assert (
        client.post(
            f"/v1/orchestrations/{oid}/cards/{card_id}/move", json={"to_column": "InProgress"}
        ).json()["status"]
        == "InProgress"
    )
    blocked = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/block", json={"reason": "dep"}
    ).json()
    assert blocked["status"] == "Blocked" and blocked["block_reason"] == "dep"
    assert (
        client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/unblock").json()["status"] == "Ready"
    )


def test_ui_and_root_served() -> None:
    client = TestClient(create_app(OrchestrationService()))
    assert client.get("/").json()["ui"] == "/ui/"
    ui = client.get("/ui/")
    assert ui.status_code == 200
    assert "ASO Runtime" in ui.text


# ------------------------------------------------ design system (wf §2.1, ADR-0034)


def test_tokens_e_components_css_sao_servidos() -> None:
    client = TestClient(create_app(OrchestrationService()))
    for asset in ("tokens.css", "components.css"):
        resposta = client.get(f"/ui/{asset}")
        assert resposta.status_code == 200
        assert "text/css" in resposta.headers["content-type"]
    tokens = client.get("/ui/tokens.css").text
    assert "--accent:#0284c7" in tokens
    componentes = client.get("/ui/components.css").text
    assert ".checklist" in componentes and ".tree" in componentes


def test_as_4_paginas_carregam_tokens_e_components() -> None:
    client = TestClient(create_app(OrchestrationService()))
    for rota in ("/ui/", "/ui/nova", "/ui/detalhe", "/ui/console"):
        pagina = client.get(rota).text
        assert "/ui/tokens.css" in pagina
        assert "/ui/components.css" in pagina
        # Tema claro (wf §2.1): nenhum resquício da paleta escura antiga na página
        # (os tokens agora moram só em tokens.css, carregado via <link>).
        assert "#0f172a" not in pagina
        assert "#38bdf8" not in pagina


# --------------------------------------------------- header de 9 elementos (ADR-0035)


def test_header_js_e_servido() -> None:
    client = TestClient(create_app(OrchestrationService()))
    resposta = client.get("/ui/header.js")
    assert resposta.status_code == 200
    assert "javascript" in resposta.headers["content-type"]
    assert "ASOHeader" in resposta.text


def test_as_4_paginas_montam_o_header_compartilhado() -> None:
    client = TestClient(create_app(OrchestrationService()))
    for rota in ("/ui/", "/ui/nova", "/ui/detalhe", "/ui/console"):
        pagina = client.get(rota).text
        assert "/ui/header.js" in pagina
        assert 'id="app-header"' in pagina
        assert "ASOHeader.mount(" in pagina


# ------------------------------------------- sidebar de 16 seções (ADR-0036)

_SECOES_SIDEBAR = (
    "dashboard",
    "demandas",
    "esteira",
    "kanban",
    "agentes",
    "modelos",
    "documentos",
    "aprovacoes",
    "execucoes",
    "testes",
    "code-reviews",
    "implantacoes",
    "incidentes",
    "auditoria",
    "metricas",
    "configuracoes",
)


def test_sidebar_js_e_servido() -> None:
    client = TestClient(create_app(OrchestrationService()))
    resposta = client.get("/ui/sidebar.js")
    assert resposta.status_code == 200
    assert "javascript" in resposta.headers["content-type"]
    assert "ASOSidebar" in resposta.text
    # As 16 seções, na ordem exata do wf §2.4.
    for secao in _SECOES_SIDEBAR:
        assert f"slug: '{secao}'" in resposta.text


def test_as_16_secoes_respondem_200_e_montam_header_e_sidebar() -> None:
    client = TestClient(create_app(OrchestrationService()))
    for secao in _SECOES_SIDEBAR:
        resposta = client.get(f"/ui/{secao}")
        assert resposta.status_code == 200, secao
        pagina = resposta.text
        assert "/ui/header.js" in pagina
        assert "/ui/sidebar.js" in pagina
        assert 'id="app-header"' in pagina
        assert 'id="app-sidebar"' in pagina
        assert f"active: '{secao}'" in pagina


def test_secao_inexistente_devolve_404() -> None:
    client = TestClient(create_app(OrchestrationService()))
    resposta = client.get("/ui/nao-existe")
    assert resposta.status_code == 404


def test_assets_compartilhados_nao_sao_interceptados_pela_rota_de_secao() -> None:
    """A rota das 16 seções é registrada por nome fixo, não path curinga —
    confirma que tokens.css/components.css/header.js/sidebar.js continuam
    caindo no mount de StaticFiles, não em `ui_secao_handler` (que devolveria
    404 para qualquer nome fora de `_SIDEBAR_SECOES`)."""
    client = TestClient(create_app(OrchestrationService()))
    for asset in ("tokens.css", "components.css", "header.js", "sidebar.js"):
        assert client.get(f"/ui/{asset}").status_code == 200


def test_rotas_antigas_continuam_validas_sem_sidebar() -> None:
    client = TestClient(create_app(OrchestrationService()))
    for rota in ("/ui/", "/ui/nova", "/ui/detalhe", "/ui/console"):
        pagina = client.get(rota).text
        assert "/ui/sidebar.js" not in pagina
        assert 'id="app-sidebar"' not in pagina
