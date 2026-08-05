"""Ficha da demanda pela API (§1/§2 do fluxo.md, ADR-0016)."""

from __future__ import annotations

import shlex

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.control.models import TRIAGE_KEY
from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile


def _cli_triagem(saida: str) -> ExecutorCatalog:
    """Catálogo com um 'agente de triagem' que apenas cospe `saida` (JSON)."""
    script = 'cat > /dev/null; printf %s "$1"; exit 0'
    comando = shlex.join(["bash", "-c", script, "_", saida])
    return ExecutorCatalog([ExecutorProfile(name="triador", kind="cli", command=comando)])


def _client(catalog: ExecutorCatalog | None = None) -> TestClient:
    return TestClient(create_app(OrchestrationService(catalog=catalog)))


def test_criacao_com_agente_de_triagem_persiste_ficha_recuperavel() -> None:
    bruto = '{"objetivo": "Login social", "dominios": ["backend", "security"], "risco": "high"}'
    client = _client(_cli_triagem(bruto))
    resposta = client.post(
        "/v1/orchestrations",
        json={"user_request": "Adicionar login social", "executor": "triador"},
    )
    assert resposta.status_code == 201
    oid = resposta.json()["id"]
    ficha = client.get(f"/v1/orchestrations/{oid}/brief").json()
    assert ficha["objetivo"] == "Login social"
    assert ficha["dominios"] == ["backend", "security"]
    assert ficha["origem"] == "triador"


def test_perguntas_abertas_aparecem_no_next_step_sem_virar_acao_primaria() -> None:
    client = _client()
    oid = client.post("/v1/orchestrations", json={"user_request": "melhorar"}).json()["id"]
    step = client.get(f"/v1/orchestrations/{oid}/next-step").json()
    bloqueio = next(b for b in step["blockers"] if b["code"] == "demanda_incompleta")
    assert bloqueio["severity"] == "aguardando_humano"
    # Sem ação própria: não pode virar `primary_action` da tela.
    assert bloqueio["action"] is None
    if step["primary_action"]:
        assert step["primary_action"]["label"] != bloqueio["title"]


def test_put_e_delete_do_agente_de_triagem() -> None:
    client = _client(ExecutorCatalog([ExecutorProfile(name="triador", kind="mock")]))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda qualquer"}).json()["id"]

    resposta = client.put(
        f"/v1/orchestrations/{oid}/agents/{TRIAGE_KEY}", json={"executor": "triador"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["agent_assignments"][TRIAGE_KEY]["executor"] == "triador"
    assert client.delete(f"/v1/orchestrations/{oid}/agents/{TRIAGE_KEY}").status_code == 200


def test_triagem_e_aceita_com_a_esteira_ja_em_f5_por_nao_ser_fase() -> None:
    client = _client(ExecutorCatalog([ExecutorProfile(name="triador", kind="mock")]))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda qualquer"}).json()["id"]
    for _ in range(4):  # F1 → F2 → F3 → F4 → F5
        assert client.post(f"/v1/orchestrations/{oid}/advance-phase").status_code == 200
    resposta = client.put(
        f"/v1/orchestrations/{oid}/agents/{TRIAGE_KEY}", json={"executor": "triador"}
    )
    assert resposta.status_code == 200


def test_post_brief_retria_e_sobrescreve_a_ficha() -> None:
    bruto = '{"objetivo": "Ficha nova", "dominios": ["frontend"]}'
    client = _client(_cli_triagem(bruto))
    # Na criação, força o agente "mock" (não produz texto): a triagem cai na heurística
    # com `fallback_reason` preenchido — sem isso o catálogo escolheria "triador" como
    # default e a ficha "antes" já sairia igual à "depois".
    oid = client.post(
        "/v1/orchestrations",
        json={"user_request": "Demanda qualquer bem detalhada aqui", "executor": "mock"},
    ).json()["id"]
    antes = client.get(f"/v1/orchestrations/{oid}/brief").json()
    assert antes["origem"] == "heuristica"
    assert antes["fallback_reason"]

    resposta = client.post(f"/v1/orchestrations/{oid}/brief", json={"executor": "triador"})
    assert resposta.status_code == 200

    depois = client.get(f"/v1/orchestrations/{oid}/brief").json()
    assert depois["origem"] == "triador"
    assert depois["objetivo"] == "Ficha nova"
    assert depois != antes


def test_rbac_get_exige_viewer_post_exige_operator() -> None:
    auth = AuthService(
        {
            "v": Principal(actor="viewer", role="viewer"),
            "o": Principal(actor="op", role="operator"),
        },
        dev_mode=False,
    )
    client = TestClient(create_app(OrchestrationService(), auth=auth))
    oid = client.post(
        "/v1/orchestrations",
        json={"user_request": "demanda qualquer"},
        headers={"Authorization": "Bearer o"},
    ).json()["id"]

    assert (
        client.get(
            f"/v1/orchestrations/{oid}/brief", headers={"Authorization": "Bearer v"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/v1/orchestrations/{oid}/brief", json={}, headers={"Authorization": "Bearer v"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/orchestrations/{oid}/brief", json={}, headers={"Authorization": "Bearer o"}
        ).status_code
        == 200
    )
