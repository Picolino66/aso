"""Comentários de revisão via API (wf §20.3, ADR-0033)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.control.review import ReviewCommentDraft, ReviewVerdict
from aso.control.triage import DemandBrief
from aso.shared.types import RiskLevel


def _orch_com_pr_e_comentario(svc: OrchestrationService) -> tuple[str, str]:
    orch = svc.create_orchestration("implementar cálculo de frete")
    card = svc.get_cards(orch.id)[0]
    pr = svc.open_pr(orch.id, card.id, branch="feat/frete-abc123")
    b = svc._bundle(orch.id)  # noqa: SLF001
    verdito = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        comentarios=[
            ReviewCommentDraft(
                arquivo="src/frete.py", linha=10, descricao="Validar entrada", obrigatorio=True
            )
        ],
    )
    svc._apply_review_verdict(b, pr, card, verdito, actor="teste")  # noqa: SLF001
    return orch.id, pr.id


def test_get_comments_lista_o_comentario_criado_pela_revisao() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid, pr_id = _orch_com_pr_e_comentario(svc)

    resposta = client.get(f"/v1/orchestrations/{oid}/pulls/{pr_id}/comments")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 1
    assert corpo[0]["arquivo"] == "src/frete.py"
    assert corpo[0]["linha"] == 10
    assert corpo[0]["status"] == "pendente"


def test_resolve_comment_via_api_marca_resolvido() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid, pr_id = _orch_com_pr_e_comentario(svc)
    comment_id = client.get(f"/v1/orchestrations/{oid}/pulls/{pr_id}/comments").json()[0]["id"]

    resposta = client.post(f"/v1/orchestrations/{oid}/pulls/{pr_id}/comments/{comment_id}/resolve")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "resolvido"


def test_resolve_comment_inexistente_devolve_404() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid, pr_id = _orch_com_pr_e_comentario(svc)

    resposta = client.post(
        f"/v1/orchestrations/{oid}/pulls/{pr_id}/comments/comment_inexistente/resolve"
    )
    assert resposta.status_code == 404


def test_resolve_comment_ja_resolvido_devolve_409() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid, pr_id = _orch_com_pr_e_comentario(svc)
    comment_id = client.get(f"/v1/orchestrations/{oid}/pulls/{pr_id}/comments").json()[0]["id"]
    client.post(f"/v1/orchestrations/{oid}/pulls/{pr_id}/comments/{comment_id}/resolve")

    resposta = client.post(f"/v1/orchestrations/{oid}/pulls/{pr_id}/comments/{comment_id}/resolve")
    assert resposta.status_code == 409


def test_next_step_aponta_comentario_obrigatorio_pendente_antes_do_merge() -> None:
    """Risco alto: `aprovado_com_sugestoes` não fecha sozinho (§4.3) — o veredito não
    é `alteracoes_obrigatorias`/`reprovado` (não dispara o bloqueio mais cedo), então
    a aprovação humana com justificativa chega ao comentário obrigatório ainda
    pendente (a auto-resolução só acontece quando o próprio veredito já aprova
    sozinho — não é este o caso, por isso o comentário nunca foi resolvido)."""
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration(
        "implementar cálculo de frete", demand_brief=DemandBrief(risco=RiskLevel.HIGH)
    )
    card = svc.get_cards(orch.id)[0]
    pr = svc.open_pr(orch.id, card.id, branch="feat/frete-abc123")
    b = svc._bundle(orch.id)  # noqa: SLF001
    verdito = ReviewVerdict(
        veredito="aprovado_com_sugestoes",
        comentarios=[
            ReviewCommentDraft(
                arquivo="src/frete.py", linha=10, descricao="Validar entrada", obrigatorio=True
            )
        ],
    )
    svc._apply_review_verdict(b, pr, card, verdito, actor="teste")  # noqa: SLF001
    oid, pr_id = orch.id, pr.id
    svc.report_ci(oid, pr_id, "passed")
    svc.report_review(oid, pr_id, "approved", justificativa="aprovação humana urgente")

    resposta = client.get(f"/v1/orchestrations/{oid}/next-step")
    assert resposta.status_code == 200
    codigos = [bl["code"] for bl in resposta.json()["blockers"]]
    assert "pr_comentario_obrigatorio_nao_resolvido" in codigos

    merge = client.post(f"/v1/orchestrations/{oid}/pulls/{pr_id}/merge")
    assert merge.status_code == 409
