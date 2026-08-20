"""CRUD de regras de roteamento via API (§33, ADR-0028) + RBAC + fluxo completo."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.control.orchestration_service import OrchestrationService


def _client(svc: OrchestrationService | None = None) -> TestClient:
    return TestClient(create_app(svc or OrchestrationService()))


def _rbac_client(svc: OrchestrationService | None = None) -> TestClient:
    auth = AuthService(
        {
            "v": Principal(actor="viewer", role="viewer"),
            "o": Principal(actor="op", role="operator"),
            "a": Principal(actor="adm", role="admin"),
        },
        dev_mode=False,
    )
    return TestClient(create_app(svc or OrchestrationService(), auth=auth))


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_REGRA_BODY = {
    "nome": "Segurança crítica",
    "descricao": "SE tipo=seguranca E risco>=high ENTÃO Opus",
    "ativa": True,
    "precedencia": 1,
    "condicoes": [
        {"campo": "tipo", "operador": "igual", "valor": "seguranca"},
        {"campo": "risco", "operador": "maior_ou_igual", "valor": "high"},
    ],
    "acao": {"modelo": "claude-opus", "effort": "max", "aprovacao_humana": True},
}


def test_crud_endpoints() -> None:
    client = _client()
    created = client.post("/v1/routing-rules", json=_REGRA_BODY)
    assert created.status_code == 201
    body = created.json()
    assert body["nome"] == "Segurança crítica"
    rule_id = body["id"]

    listed = client.get("/v1/routing-rules").json()
    assert any(r["id"] == rule_id for r in listed)

    updated = client.put(
        f"/v1/routing-rules/{rule_id}",
        json={**_REGRA_BODY, "nome": "Segurança crítica v2"},
    )
    assert updated.status_code == 200
    assert updated.json()["nome"] == "Segurança crítica v2"

    deleted = client.delete(f"/v1/routing-rules/{rule_id}")
    assert deleted.status_code == 200
    assert not any(r["id"] == rule_id for r in client.get("/v1/routing-rules").json())


def test_criar_regra_sem_condicao_devolve_400() -> None:
    client = _client()
    resposta = client.post("/v1/routing-rules", json={**_REGRA_BODY, "condicoes": []})
    assert resposta.status_code == 400


def test_atualizar_regra_inexistente_devolve_404() -> None:
    client = _client()
    resposta = client.put("/v1/routing-rules/route_inexistente", json=_REGRA_BODY)
    assert resposta.status_code == 404


def test_deletar_regra_inexistente_devolve_404() -> None:
    client = _client()
    resposta = client.delete("/v1/routing-rules/route_inexistente")
    assert resposta.status_code == 404


def test_rbac_escrita_exige_admin_leitura_aberta_a_viewer() -> None:
    client = _rbac_client()
    # viewer lê
    assert client.get("/v1/routing-rules", headers=_h("v")).status_code == 200
    # viewer não escreve
    assert client.post("/v1/routing-rules", json=_REGRA_BODY, headers=_h("v")).status_code == 403
    # operator também não pode escrever regra de roteamento (mesmo nível de /executors)
    assert client.post("/v1/routing-rules", json=_REGRA_BODY, headers=_h("o")).status_code == 403
    # admin cria
    created = client.post("/v1/routing-rules", json=_REGRA_BODY, headers=_h("a"))
    assert created.status_code == 201
    rule_id = created.json()["id"]
    assert (
        client.put(f"/v1/routing-rules/{rule_id}", json=_REGRA_BODY, headers=_h("o")).status_code
        == 403
    )
    assert client.delete(f"/v1/routing-rules/{rule_id}", headers=_h("o")).status_code == 403
    assert client.delete(f"/v1/routing-rules/{rule_id}", headers=_h("a")).status_code == 200


def test_fluxo_completo_regra_criada_via_api_influencia_orquestracao_criada_via_api() -> None:
    """Cria a regra via API, depois cria uma orquestração cuja ficha casa com ela,
    e confirma que o plano resultante refletiu a regra (não só a heurística).

    A condição usa `dominios`/`risco` (não `tipo`): sem agente de triagem
    configurado, `POST /v1/orchestrations` tria por heurística
    (`triage.py::_heuristica`), que nunca classifica `tipo="seguranca"` por
    palavra-chave — só eleva domínio/risco. `tipo` só existe pelo caminho do
    agente (`_sanear`).
    """
    client = _client()
    regra_dominio = {
        **_REGRA_BODY,
        "condicoes": [
            {"campo": "dominios", "operador": "contem", "valor": "security"},
            {"campo": "risco", "operador": "maior_ou_igual", "valor": "high"},
        ],
    }
    created = client.post("/v1/routing-rules", json=regra_dominio)
    assert created.status_code == 201

    orch = client.post(
        "/v1/orchestrations",
        json={"user_request": "corrigir login com token e senha vazados, risco de segurança"},
    )
    assert orch.status_code == 201
    body = orch.json()
    assert body["routing_rule_applied"] is not None
    assert body["routing_rule_applied"]["regra_nome"] == "Segurança crítica"
    assert body["selected_executor"] == "claude-opus"
    assert body["selected_effort"] == "max"


def test_reorder_reatribui_precedencia_na_ordem_recebida() -> None:
    client = _client()
    a = client.post("/v1/routing-rules", json={**_REGRA_BODY, "nome": "A", "precedencia": 5}).json()
    b = client.post("/v1/routing-rules", json={**_REGRA_BODY, "nome": "B", "precedencia": 1}).json()
    c = client.post("/v1/routing-rules", json={**_REGRA_BODY, "nome": "C", "precedencia": 3}).json()

    resposta = client.put("/v1/routing-rules/reorder", json={"ordem": [b["id"], c["id"], a["id"]]})
    assert resposta.status_code == 200
    corpo = resposta.json()
    por_id = {r["id"]: r for r in corpo}
    assert por_id[b["id"]]["precedencia"] == 10
    assert por_id[c["id"]]["precedencia"] == 20
    assert por_id[a["id"]]["precedencia"] == 30

    listadas = sorted(client.get("/v1/routing-rules").json(), key=lambda r: r["precedencia"])
    assert [r["nome"] for r in listadas] == ["B", "C", "A"]


def test_reorder_com_id_inexistente_devolve_404() -> None:
    client = _client()
    resposta = client.put("/v1/routing-rules/reorder", json={"ordem": ["route_fantasma"]})
    assert resposta.status_code == 404


def test_reorder_nao_e_interceptado_por_put_de_id() -> None:
    """Regressão de roteamento: `PUT .../reorder` precisa ir para o handler de
    reorder, não para `PUT .../{rule_id}` com `rule_id='reorder'` (ADR-0042)."""
    client = _client()
    resposta = client.put("/v1/routing-rules/reorder", json={"ordem": []})
    assert resposta.status_code == 200
    assert resposta.json() == []


def test_preview_devolve_demandas_que_casariam() -> None:
    client = _client()
    client.post(
        "/v1/orchestrations",
        json={
            "user_request": "demanda de segurança",
            "demand_brief": {"tipo": "seguranca", "risco": "high", "dominios": ["security"]},
        },
    )
    client.post("/v1/orchestrations", json={"user_request": "demanda comum"})

    resposta = client.post(
        "/v1/routing-rules/preview",
        json={
            "condicoes": [
                {"campo": "tipo", "operador": "igual", "valor": "seguranca"},
                {"campo": "risco", "operador": "maior_ou_igual", "valor": "high"},
            ]
        },
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 1
    assert corpo[0]["user_request"] == "demanda de segurança"
    assert corpo[0]["tipo"] == "seguranca"


def test_preview_sem_condicao_devolve_400() -> None:
    client = _client()
    resposta = client.post("/v1/routing-rules/preview", json={"condicoes": []})
    assert resposta.status_code == 400


def test_rbac_preview_e_reorder_exigem_admin() -> None:
    client = _rbac_client()
    assert (
        client.post(
            "/v1/routing-rules/preview", json={"condicoes": []}, headers=_h("v")
        ).status_code
        == 403
    )
    assert (
        client.put("/v1/routing-rules/reorder", json={"ordem": []}, headers=_h("o")).status_code
        == 403
    )
