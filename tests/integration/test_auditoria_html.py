"""Conteúdo da Tela 28 (Auditoria com filtros) — wf §30, ADR-0051."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_auditoria_nao_e_mais_placeholder() -> None:
    pagina = _client().get("/ui/auditoria").text
    assert "active: 'auditoria'" in pagina
    assert "FID-24" not in pagina


def test_auditoria_tem_os_seis_filtros() -> None:
    pagina = _client().get("/ui/auditoria").text
    filtros = ["fDataDe", "fDataAte", "fProjeto", "fDemanda", "fAgente", "fEtapa", "fResultado"]
    for filtro in filtros:
        assert filtro in pagina, filtro


def test_auditoria_consome_endpoint_real_e_tem_exportacao() -> None:
    pagina = _client().get("/ui/auditoria").text
    assert "/v1/audit" in pagina
    assert "/v1/audit/export" in pagina


def test_auditoria_tem_paginacao() -> None:
    pagina = _client().get("/ui/auditoria").text
    assert "btnAnterior" in pagina
    assert "btnProxima" in pagina
