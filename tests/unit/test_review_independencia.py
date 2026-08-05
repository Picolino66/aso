"""Independência real da revisão (§14, ADR-0017).

Cobre a regra central do incremento: o revisor nunca pode ser o mesmo executor que
implementou o card, `report_review("approved")` nunca aceita sem veredito aprovado
ou justificativa humana, e a aprovação automática respeita o risco da demanda (§4.3).
"""

from __future__ import annotations

import pytest

from aso.control.orchestration_service import OrchestrationService
from aso.control.review import VEREDITO_NECESSITA_HUMANO, exige_confirmacao_humana
from aso.control.triage import DemandBrief
from aso.shared.types import RiskLevel


def _orch_com_pr(svc: OrchestrationService) -> tuple[str, str]:
    orch = svc.create_orchestration("implementar cálculo de frete")
    card = svc.get_cards(orch.id)[0]
    pr = svc.open_pr(orch.id, card.id, branch="feat/frete-abc123")
    return orch.id, pr.id


# ------------------------------------------------------- independência do revisor


def test_revisor_igual_ao_executor_do_card_recusa_sem_git() -> None:
    """A recusa acontece ANTES de tocar o workspace: nenhuma orquestração de teste
    aqui precisa de repositório git real."""
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    card = svc.get_cards(orch_id)[0]
    card.executor = "codex-gpt-5-high"

    pr = svc.run_review(orch_id, pr_id, executor="codex-gpt-5-high")

    assert pr.review_verdict["veredito"] == VEREDITO_NECESSITA_HUMANO
    assert pr.review_verdict["origem"] == "indisponivel"
    assert "mesmo executor" in pr.review_verdict["fallback_reason"]
    assert pr.review_status != "approved"


def test_sem_revisor_disponivel_recusa_sem_aprovar() -> None:
    svc = OrchestrationService()  # sem catálogo: nenhum default para resolver
    orch_id, pr_id = _orch_com_pr(svc)

    pr = svc.run_review(orch_id, pr_id)

    assert pr.review_verdict["veredito"] == VEREDITO_NECESSITA_HUMANO
    assert "nenhum agente revisor configurado" in pr.review_verdict["fallback_reason"]


def test_run_review_de_pr_inexistente_leva_a_erro() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    with pytest.raises(KeyError):
        svc.run_review(orch.id, "pr-inexistente")


# --------------------------------------------------------- report_review governado


def test_aprovar_sem_veredito_e_sem_justificativa_e_recusado() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    with pytest.raises(ValueError, match="revisão"):
        svc.report_review(orch_id, pr_id, "approved")


def test_aprovar_com_veredito_aprovado_e_aceito() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    pr = svc.list_pulls(orch_id)[0]
    pr.review_verdict = {"veredito": "aprovado", "origem": "agente"}

    resultado = svc.report_review(orch_id, pr_id, "approved")
    assert resultado.review_status == "approved"


def test_aprovar_com_justificativa_e_aceito_e_registra_actor() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)

    resultado = svc.report_review(
        orch_id, pr_id, "approved", actor="humano-admin", justificativa="risco aceito manualmente"
    )
    assert resultado.review_status == "approved"

    eventos = [e for e in svc.timeline(orch_id) if e.type == "ReviewReported"]
    assert eventos
    assert eventos[-1].payload["actor"] == "humano-admin"
    assert eventos[-1].payload["justificativa"] == "risco aceito manualmente"


def test_aprovar_com_veredito_de_alteracoes_obrigatorias_e_recusado_sem_justificativa() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    pr = svc.list_pulls(orch_id)[0]
    pr.review_verdict = {"veredito": "alteracoes_obrigatorias", "origem": "agente"}
    with pytest.raises(ValueError):
        svc.report_review(orch_id, pr_id, "approved")


# ---------------------------------------------------------- exige_confirmacao_humana


@pytest.mark.parametrize(
    ("risco", "impactos", "esperado"),
    [
        (RiskLevel.LOW, [], False),
        (RiskLevel.MEDIUM, [], False),
        (RiskLevel.MEDIUM, ["contract"], False),
        (RiskLevel.HIGH, [], True),
        (RiskLevel.CRITICAL, [], True),
        (RiskLevel.LOW, ["security"], True),
        (RiskLevel.LOW, ["database"], True),
        (RiskLevel.LOW, ["deploy"], True),
        (RiskLevel.LOW, ["architecture"], False),
    ],
)
def test_exige_confirmacao_humana_matriz(
    risco: RiskLevel, impactos: list[str], esperado: bool
) -> None:
    brief = DemandBrief(risco=risco, impactos=impactos)
    assert exige_confirmacao_humana(brief) is esperado
