"""Conteúdo de /ui/documentos (Tela 08/09, wf §10/§11) — ADR-0046."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_documentos_sem_id_mostra_picker() -> None:
    pagina = _client().get("/ui/documentos").text
    assert "listaPicker" in pagina
    assert 'id="app-header"' in pagina
    assert "active: 'documentos'" in pagina


def test_documentos_com_id_consome_endpoints_reais() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/documentos?id={oid}").text
    assert "/documentos" in pagina
    assert "/documentos/' + tipo + '/history" in pagina
    assert "/documentos/' + tipo + '/diff" in pagina
    assert "/documentos/' + tipo + '/comments" in pagina
    assert "/documentos/' + tipo + '/review" in pagina


def test_documentos_tem_editor_markdown_e_preview() -> None:
    pagina = _client().get("/ui/documentos").text
    assert "mdEditor" in pagina
    assert "mdPreview" in pagina
    assert "renderizarMarkdown" in pagina


def test_documentos_tem_comparacao_de_versoes() -> None:
    pagina = _client().get("/ui/documentos").text
    assert "compararVersoes" in pagina
    assert "diffDe" in pagina
    assert "diffPara" in pagina


def test_documentos_tem_checklist_do_revisor() -> None:
    pagina = _client().get("/ui/documentos").text
    assert "rodarRevisao" in pagina
    assert "resultadoRevisao" in pagina


def test_documentos_tem_comentarios_com_oito_campos() -> None:
    pagina = _client().get("/ui/documentos").text
    for campo in ["comAutor", "comTipo", "comSeveridade", "comTrecho", "comDescricao", "comAcao"]:
        assert campo in pagina
    assert "resolver-comentario" in pagina


def test_documentos_link_de_volta_para_demanda_detalhe() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/documentos?id={oid}").text
    assert "/ui/demanda-detalhe?id=" in pagina
