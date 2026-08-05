"""Gate de risco contornável — pendência da ADR-0017, corrigida na ADR-0019 (§4.7).

Achado da avaliação do Incremento B: `report_review("approved")` só checava se havia
um veredito aprovado, nunca se o RISCO da demanda exigia confirmação humana — em
demanda de alto risco, o agente aprovando bastava para fechar a revisão, e
`required_role` declarava `admin` num bloqueio que a API nunca cobrava. Este arquivo
prova que o bug não volta.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.shared.types import RiskLevel


def _orch_com_pr(svc: OrchestrationService, *, risco: RiskLevel) -> tuple[str, str]:
    orch = svc.create_orchestration(
        "implementar cálculo de frete", demand_brief=DemandBrief(risco=risco)
    )
    card = svc.get_cards(orch.id)[0]
    pr = svc.open_pr(orch.id, card.id, branch="feat/frete-abc123")
    return orch.id, pr.id


def test_risco_alto_com_veredito_aprovado_sem_justificativa_e_recusado() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc, risco=RiskLevel.HIGH)
    pr = svc.list_pulls(orch_id)[0]
    pr.review_verdict = {"veredito": "aprovado", "origem": "agente"}

    try:
        svc.report_review(orch_id, pr_id, "approved")
    except ValueError as exc:
        assert "risco" in str(exc).lower()
    else:
        raise AssertionError("deveria recusar sem justificativa")


def test_risco_alto_com_justificativa_e_aceito() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc, risco=RiskLevel.HIGH)
    pr = svc.list_pulls(orch_id)[0]
    pr.review_verdict = {"veredito": "aprovado", "origem": "agente"}

    resultado = svc.report_review(
        orch_id, pr_id, "approved", justificativa="risco avaliado e aceito manualmente"
    )
    assert resultado.review_status == "approved"


def test_risco_baixo_com_veredito_aprovado_nao_regride_o_caminho_feliz() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc, risco=RiskLevel.LOW)
    pr = svc.list_pulls(orch_id)[0]
    pr.review_verdict = {"veredito": "aprovado", "origem": "agente"}

    resultado = svc.report_review(orch_id, pr_id, "approved")
    assert resultado.review_status == "approved"


def test_risco_critico_com_veredito_aprovado_sem_justificativa_e_recusado() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc, risco=RiskLevel.CRITICAL)
    pr = svc.list_pulls(orch_id)[0]
    pr.review_verdict = {"veredito": "aprovado", "origem": "agente"}

    try:
        svc.report_review(orch_id, pr_id, "approved")
    except ValueError:
        pass
    else:
        raise AssertionError("deveria recusar sem justificativa")


def test_nao_admin_com_justificativa_recebe_403() -> None:
    """A checagem fina de papel fica no handler da API (`required_role` não enxerga o
    corpo da requisição) — não-admin não aprova com justificativa mesmo com token
    válido de operator."""
    auth = AuthService(
        {
            "o": Principal(actor="op", role="operator"),
            "a": Principal(actor="adm", role="admin"),
        },
        dev_mode=False,
    )
    svc = OrchestrationService()
    client = TestClient(create_app(svc, auth=auth))
    oid = client.post(
        "/v1/orchestrations",
        json={"user_request": "ajustar autenticação e senha de login"},
        headers={"Authorization": "Bearer a"},
    ).json()["id"]
    card_id = client.get(
        f"/v1/orchestrations/{oid}/cards", headers={"Authorization": "Bearer a"}
    ).json()[0]["id"]
    pr = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/open-pr",
        json={},
        headers={"Authorization": "Bearer a"},
    ).json()
    pr_id = pr["id"]

    resposta = client.post(
        f"/v1/orchestrations/{oid}/pulls/{pr_id}/review",
        json={"status": "approved", "justificativa": "confio no agente"},
        headers={"Authorization": "Bearer o"},
    )
    assert resposta.status_code == 403
