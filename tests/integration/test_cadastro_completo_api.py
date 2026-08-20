"""API da Tela 03 (Cadastro de demanda completo, wf §5.2) — ADR-0039."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_create_com_demand_brief_completo_pula_a_triagem() -> None:
    client = _client()
    resposta = client.post(
        "/v1/orchestrations",
        json={
            "user_request": "implementar cálculo de frete internacional",
            "demand_brief": {
                "tipo": "funcionalidade",
                "solicitante": "Maria",
                "origem_da_demanda": "ticket #123",
                "risco": "high",
                "complexidade": "complexa",
                "aprovacao_humana_obrigatoria": True,
            },
        },
    )
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["demand_brief"]["solicitante"] == "Maria"
    assert corpo["demand_brief"]["risco"] == "high"
    # Sem re-triagem: `fallback_reason`/`origem` não foram tocados pelo TriageService.
    assert corpo["demand_brief"]["origem"] == "heuristica"
    assert corpo["demand_brief"]["fallback_reason"] == ""


def test_create_com_demand_brief_forca_aprovacao_humana() -> None:
    client = _client()
    oid = client.post(
        "/v1/orchestrations",
        json={
            "user_request": "demanda de baixo risco",
            "demand_brief": {"risco": "low", "aprovacao_humana_obrigatoria": True},
        },
    ).json()["id"]
    aprovacoes = client.get(f"/v1/orchestrations/{oid}/approvals").json()
    assert any(a["status"] == "pending" for a in aprovacoes)


def test_create_com_orcamento_usd_na_criacao() -> None:
    client = _client()
    resposta = client.post(
        "/v1/orchestrations", json={"user_request": "demanda com orçamento", "orcamento_usd": 100.0}
    )
    assert resposta.json()["orcamento_usd"] == 100.0


def test_create_com_demand_brief_propaga_classificacao_ao_planejador() -> None:
    """Bug real (code-review ultra): faltava `decision_input=` na criação via
    `demand_brief` — o planejador/`_apply_routing_rule` viam sempre
    `domains=["backend"]` (default), ignorando os domínios preenchidos à mão no
    formulário da Tela 03. Com `dominios=["frontend"]` e nenhum "backend", o card
    seedado deve ir para `FrontendDevelopmentAgent`, nunca `BackendDevelopmentAgent`."""
    client = _client()
    resposta = client.post(
        "/v1/orchestrations",
        json={
            "user_request": "implementar tela de checkout",
            "demand_brief": {"tipo": "funcionalidade", "dominios": ["frontend"], "risco": "low"},
        },
    )
    assert resposta.status_code == 201
    oid = resposta.json()["id"]
    cards = client.get(f"/v1/orchestrations/{oid}/cards").json()
    assignees = {c["assignee"] for c in cards}
    assert "FrontendDevelopmentAgent" in assignees
    assert "BackendDevelopmentAgent" not in assignees


def test_create_sem_demand_brief_continua_triando_normalmente() -> None:
    """Regressão: o fluxo antigo (`nova.html`, sem `demand_brief` no corpo)
    continua chamando `create_with_triage` como sempre."""
    client = _client()
    resposta = client.post("/v1/orchestrations", json={"user_request": "implementar algo qualquer"})
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["demand_brief"]  # ficha não fica vazia (triagem rodou)
