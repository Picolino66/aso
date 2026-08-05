"""QA humano pela API (§16/§17 do fluxo.md, ADR-0025)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.shared.types import Phase, RiskLevel


def _orch(svc: OrchestrationService) -> tuple[str, str]:
    orch = svc.create_orchestration(
        "ajustar tela de checkout", demand_brief=DemandBrief(dominios=["frontend"])
    )
    card = svc.get_cards(orch.id)[0]
    return orch.id, card.id


def test_fluxo_completo_registrar_reprovar_bug_e_bloqueio() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid, card_id = _orch(svc)

    vazio = client.get(f"/v1/orchestrations/{oid}/cards/{card_id}/qa")
    assert vazio.status_code == 200
    assert vazio.json() == []

    registrado = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/qa",
        json={
            "cenario": "checkout com cupom",
            "passos": ["abrir carrinho", "aplicar cupom"],
            "resultado_esperado": "desconto aplicado",
            "gravidade": "alta",
        },
    )
    assert registrado.status_code == 200
    assert registrado.json()["status"] == "pendente"

    reprovado = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/qa/0/fail",
        json={"resultado_obtido": "cupom não aplicou desconto"},
    )
    assert reprovado.status_code == 200
    assert reprovado.json()["status"] in ("NeedsFix", "Failed")

    checks = client.get(f"/v1/orchestrations/{oid}/cards/{card_id}/qa").json()
    assert checks[0]["status"] == "falhou"

    cards = client.get(f"/v1/orchestrations/{oid}/cards").json()
    bug = next(c for c in cards if c["type"] == "Bug")
    assert bug["parent_id"] == card_id
    assert bug["dependencies"] == [card_id]
    assert bug["priority"] == "high"


def test_fail_indice_invalido_devolve_404() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid, card_id = _orch(svc)
    resposta = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/qa/0/fail", json={})
    assert resposta.status_code == 404


def test_rbac_get_viewer_post_operator() -> None:
    auth = AuthService(
        {
            "v": Principal(actor="view", role="viewer"),
            "o": Principal(actor="op", role="operator"),
        },
        dev_mode=False,
    )
    svc = OrchestrationService()
    client = TestClient(create_app(svc, auth=auth))
    oid, card_id = _orch(svc)

    assert (
        client.get(
            f"/v1/orchestrations/{oid}/cards/{card_id}/qa", headers={"Authorization": "Bearer v"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/v1/orchestrations/{oid}/cards/{card_id}/qa",
            json={"cenario": "x"},
            headers={"Authorization": "Bearer v"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/orchestrations/{oid}/cards/{card_id}/qa",
            json={"cenario": "x"},
            headers={"Authorization": "Bearer o"},
        ).status_code
        == 200
    )


def test_qa_pendente_aparece_no_next_step_para_dominio_frontend() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid, card_id = _orch(svc)
    svc.move_card(oid, card_id, "Testing")
    svc.get(oid).current_phase = Phase.F5  # o card seed nasce em F5

    relatorio = client.get(f"/v1/orchestrations/{oid}/next-step").json()
    codigos = [b["code"] for b in relatorio["blockers"]]
    assert "qa_pendente" in codigos

    svc.register_qa_check(oid, card_id, cenario="checkout", status="passou")
    relatorio2 = client.get(f"/v1/orchestrations/{oid}/next-step").json()
    codigos2 = [b["code"] for b in relatorio2["blockers"]]
    assert "qa_pendente" not in codigos2


def test_priority_baixa_e_media_mapeiam_corretamente() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    svc.register_qa_check(orch.id, card.id, cenario="a", gravidade="baixa")
    svc.register_qa_check(orch.id, card.id, cenario="b", gravidade="critica")
    svc.fail_qa_check(orch.id, card.id, 0)
    svc.fail_qa_check(orch.id, card.id, 1)
    bugs = [c for c in svc.get_cards(orch.id) if c.type.value == "Bug"]
    prioridades = {b.priority for b in bugs}
    assert RiskLevel.LOW in prioridades
    assert RiskLevel.CRITICAL in prioridades
