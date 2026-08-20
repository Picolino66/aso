"""Conteúdo das Telas 15/16/17 (execução, quality gates, falhas) — ADR-0048."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_card_detalhe_tem_aba_falhas() -> None:
    pagina = _client().get("/ui/card-detalhe").text
    assert "'Falhas'" in pagina


def test_card_detalhe_tem_os_oito_controles_em_voo() -> None:
    pagina = _client().get("/ui/card-detalhe").text
    for controle in [
        "ctlPausar",
        "ctlCancelar",
        "ctlEffort",
        "ctlModelo",
        "ctlContexto",
        "ctlAjuda",
        "ctlTransferir",
        "ctlBloquear",
    ]:
        assert controle in pagina, controle


def test_card_detalhe_consome_endpoints_novos() -> None:
    pagina = _client().get("/ui/card-detalhe").text
    assert "/increase-effort" in pagina
    assert "/transfer-model" in pagina
    assert "/add-context" in pagina
    assert "/request-help" in pagina
    assert "/pause" in pagina
    assert "/changed-files" in pagina
    assert "/failure-diagnostics" in pagina


def test_card_detalhe_tem_as_sete_decisoes_do_orquestrador() -> None:
    pagina = _client().get("/ui/card-detalhe").text
    for decisao in [
        "Manter o mesmo agente",
        "Trocar agente",
        "Trocar modelo",
        "Aumentar effort",
        "Criar investigação separada",
        "Solicitar revisão humana",
        "Bloquear (card)",
    ]:
        assert decisao in pagina, decisao
    assert "disabled" in pagina  # "Criar investigação separada" desabilitado


def test_card_detalhe_tem_tabela_de_quality_gates_com_duracao() -> None:
    pagina = _client().get("/ui/card-detalhe").text
    assert "Duração" in pagina
    assert "duration_ms" in pagina


def test_execucoes_sem_id_mostra_picker() -> None:
    pagina = _client().get("/ui/execucoes").text
    assert "listaPicker" in pagina
    assert "active: 'execucoes'" in pagina


def test_execucoes_com_id_consome_endpoint_real() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/execucoes?id={oid}").text
    assert "/cards'" in pagina
    assert "/ui/card-detalhe?id=" in pagina


def test_testes_sem_id_mostra_picker() -> None:
    pagina = _client().get("/ui/testes").text
    assert "listaPicker" in pagina
    assert "active: 'testes'" in pagina


def test_testes_com_id_consome_quality_gates() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/testes?id={oid}").text
    assert "/quality-gates'" in pagina
    assert "FID-22" in pagina  # limitação honesta do escopo compartilhado


def test_demanda_detalhe_linka_para_execucoes_e_testes_agregados() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/demanda-detalhe?id={oid}").text
    assert "/ui/execucoes?id=" in pagina
    assert "/ui/testes?id=" in pagina
