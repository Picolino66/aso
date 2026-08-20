"""Conteúdo da Tela 30 (Configuração de agentes) — wf §32, ADR-0053."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_agentes_nao_e_mais_placeholder() -> None:
    pagina = _client().get("/ui/agentes").text
    assert "active: 'agentes'" in pagina
    assert "FID-26" not in pagina


def test_agentes_tem_os_treze_campos_no_editor() -> None:
    pagina = _client().get("/ui/agentes").text
    for campo in [
        "campoNome",
        "campoTipo",
        "campoFuncao",
        "campoPlataforma",
        "campoRole",
        "campoModelos",
        "campoEfforts",
        "campoFerramentas",
        "campoPermissoes",
        "campoProjetos",
        "campoCategorias",
        "campoLimiteCusto",
        "campoLimiteTentativas",
        "campoSupervisao",
    ]:
        assert campo in pagina, campo


def test_agentes_consome_endpoints_reais() -> None:
    pagina = _client().get("/ui/agentes").text
    assert "/v1/agent-definitions" in pagina
    assert "/v1/agent-definitions/roles" in pagina
    assert "/v1/me" in pagina


def test_agentes_tem_nota_de_permissao_somente_leitura() -> None:
    pagina = _client().get("/ui/agentes").text
    assert "notaSomenteLeitura" in pagina
    assert "admin" in pagina
