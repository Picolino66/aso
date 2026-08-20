"""Conteúdo das Telas 22-27 (aprovação, pipeline, saúde, rollback, aceite,
encerramento) — ADR-0050."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_demanda_detalhe_tem_aba_encerramento() -> None:
    pagina = _client().get("/ui/demanda-detalhe").text
    assert "'Encerramento'" in pagina


def test_demanda_detalhe_deploys_tem_controles_das_telas_22_a_25() -> None:
    pagina = _client().get("/ui/demanda-detalhe").text
    for controle in [
        "btnRodarDeploy",
        "btnValidarDeploy",
        "formAprovarDeploy",
        "formReverterDeploy",
        "deploy/approval-checklist",
        "deploy/health",
        "deploy/rollback-checklist",
    ]:
        assert controle in pagina, controle


def test_demanda_detalhe_tem_as_seis_estrategias_de_rollback() -> None:
    pagina = _client().get("/ui/demanda-detalhe").text
    for estrategia in [
        "Voltar versão",
        "Reverter configuração",
        "Desabilitar feature flag",
        "Restaurar banco",
        "Suspender filas",
        "Desativar integração",
    ]:
        assert estrategia in pagina, estrategia


def test_demanda_detalhe_tem_os_tres_tipos_extras_de_aceite() -> None:
    pagina = _client().get("/ui/demanda-detalhe").text
    for tipo in ["Aceite de produto", "Aceite técnico", "Aceite de negócio"]:
        assert tipo in pagina, tipo


def test_demanda_detalhe_incidentes_tem_acoes_de_investigar_resolver() -> None:
    pagina = _client().get("/ui/demanda-detalhe").text
    assert "btn-investigar" in pagina
    assert "btn-resolver" in pagina


def test_demanda_detalhe_encerramento_consome_closure_e_tem_export() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/demanda-detalhe?id={oid}").text
    assert "/closure'" in pagina
    assert "/closure/export" in pagina


def test_implantacoes_sem_id_mostra_picker() -> None:
    pagina = _client().get("/ui/implantacoes").text
    assert "listaPicker" in pagina
    assert "active: 'implantacoes'" in pagina


def test_implantacoes_com_id_consome_endpoint_real() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    pagina = client.get(f"/ui/implantacoes?id={oid}").text
    assert "/deploy/history'" in pagina
    assert "/ui/demanda-detalhe?id=" in pagina


def test_aprovacoes_e_uma_inbox_real_cross_demanda() -> None:
    pagina = _client().get("/ui/aprovacoes").text
    assert "active: 'aprovacoes'" in pagina
    assert "/v1/approvals" in pagina
    assert "FID-23" not in pagina  # não é mais placeholder
    assert "FID-18" not in pagina
