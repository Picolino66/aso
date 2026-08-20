"""Comentário de revisão ancorado em arquivo/linha (wf §20.3) — ADR-0033.

Cobre: `_apply_review_verdict` promove `ReviewCommentDraft` a `ReviewComment` de
primeira classe; auto-resolução quando uma rodada aprova; `correction_actions`
derivadas dos comentários (com fallback legado); bloqueio do merge por comentário
obrigatório pendente; resolução manual e suas guardas; listagem por PR.
"""

from __future__ import annotations

import pytest

from aso.control.orchestration_service import OrchestrationService
from aso.control.review import ReviewAction, ReviewCommentDraft, ReviewVerdict


def _orch_com_pr(svc: OrchestrationService) -> tuple[str, str]:
    orch = svc.create_orchestration("implementar cálculo de frete")
    card = svc.get_cards(orch.id)[0]
    pr = svc.open_pr(orch.id, card.id, branch="feat/frete-abc123")
    return orch.id, pr.id


def _aplicar(svc: OrchestrationService, orch_id: str, pr_id: str, verdito: ReviewVerdict) -> None:
    b = svc._bundle(orch_id)  # noqa: SLF001
    pr = next(p for p in b.pull_requests if p.id == pr_id)
    card = b.board_service.get_card(pr.card_id)
    assert card is not None
    svc._apply_review_verdict(b, pr, card, verdito, actor="teste")  # noqa: SLF001


# --------------------------------------------------------------------- criação


def test_apply_review_verdict_promove_comentarios_a_entidade_de_primeira_classe() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    verdito = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        comentarios=[
            ReviewCommentDraft(
                arquivo="src/frete.py",
                linha=10,
                categoria="seguranca",
                severidade="alta",
                descricao="Validar entrada do usuário",
                sugestao="use um schema",
                obrigatorio=True,
            )
        ],
    )
    _aplicar(svc, orch_id, pr_id, verdito)

    comentarios = svc.list_review_comments(orch_id, pr_id)
    assert len(comentarios) == 1
    c = comentarios[0]
    assert c.orchestration_id == orch_id
    assert c.pr_id == pr_id
    assert c.card_id is not None
    assert c.arquivo == "src/frete.py"
    assert c.linha == 10
    assert c.categoria == "seguranca"
    assert c.severidade == "alta"
    assert c.descricao == "Validar entrada do usuário"
    assert c.sugestao == "use um schema"
    assert c.obrigatorio is True
    assert c.status == "pendente"
    assert c.review_round == 1


def test_severidade_do_comentario_e_independente_da_severidade_da_acao() -> None:
    """`ReviewAction.severidade` (obrigatoria/sugestao) e `ReviewComment.severidade`
    (gravidade) são campos distintos que podem coexistir sem conflito."""
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    verdito = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        acoes=[ReviewAction(descricao="corrigir X", severidade="obrigatoria")],
        comentarios=[
            ReviewCommentDraft(arquivo="x.py", descricao="corrigir X", severidade="critica")
        ],
    )
    _aplicar(svc, orch_id, pr_id, verdito)
    assert svc.list_review_comments(orch_id, pr_id)[0].severidade == "critica"


# ---------------------------------------------------------- auto-resolução (§15)


def test_rodada_aprovada_resolve_automaticamente_comentarios_pendentes() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    reprovado = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        comentarios=[
            ReviewCommentDraft(arquivo="a.py", descricao="obrigatório", obrigatorio=True),
            ReviewCommentDraft(arquivo="b.py", descricao="sugestão", obrigatorio=False),
        ],
    )
    _aplicar(svc, orch_id, pr_id, reprovado)
    assert all(c.status == "pendente" for c in svc.list_review_comments(orch_id, pr_id))

    aprovado = ReviewVerdict(veredito="aprovado")
    _aplicar(svc, orch_id, pr_id, aprovado)

    comentarios = svc.list_review_comments(orch_id, pr_id)
    assert all(c.status == "resolvido" for c in comentarios)
    assert all(c.resolved_by == "system" for c in comentarios)
    assert all(c.resolved_at is not None for c in comentarios)


def test_rodada_aprovada_com_risco_alto_nao_auto_resolve() -> None:
    """§4.3: risco alto não fecha a revisão sozinho — a auto-resolução (que só
    acontece quando `review_status` vira `approved`) também fica pendente."""
    from aso.control.triage import DemandBrief
    from aso.shared.types import RiskLevel

    svc = OrchestrationService()
    orch = svc.create_orchestration(
        "implementar cálculo de frete", demand_brief=DemandBrief(risco=RiskLevel.CRITICAL)
    )
    card = svc.get_cards(orch.id)[0]
    pr = svc.open_pr(orch.id, card.id, branch="feat/frete-abc123")
    reprovado = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        comentarios=[ReviewCommentDraft(arquivo="a.py", descricao="x", obrigatorio=True)],
    )
    _aplicar(svc, orch.id, pr.id, reprovado)
    aprovado = ReviewVerdict(veredito="aprovado")
    _aplicar(svc, orch.id, pr.id, aprovado)
    assert svc.list_review_comments(orch.id, pr.id)[0].status == "pendente"


# --------------------------------------------------------- correction_actions


def test_correction_actions_derivadas_dos_comentarios_quando_existem() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    verdito = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        acoes=[ReviewAction(descricao="ação legada — não deve aparecer")],
        comentarios=[
            ReviewCommentDraft(arquivo="a.py", descricao="corrigir A", obrigatorio=True),
            ReviewCommentDraft(arquivo="b.py", descricao="sugestão B", obrigatorio=False),
        ],
    )
    _aplicar(svc, orch_id, pr_id, verdito)
    b = svc._bundle(orch_id)  # noqa: SLF001
    card = b.board_service.get_card(svc.get_cards(orch_id)[0].id)
    assert card is not None
    assert card.correction_actions == ["corrigir A"]


def test_correction_actions_cai_no_legado_sem_comentarios() -> None:
    """Agente que só devolve `acoes` (comportamento anterior à ADR-0033) preserva o
    caminho antigo — critério de aceite 'review agregado atual continua válido'."""
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    verdito = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        acoes=[ReviewAction(descricao="corrigir X", severidade="obrigatoria")],
    )
    _aplicar(svc, orch_id, pr_id, verdito)
    card = svc.get_cards(orch_id)[0]
    assert card.correction_actions == ["corrigir X"]


# ------------------------------------------------------------------- merge_pr


def test_merge_pr_bloqueia_comentario_obrigatorio_pendente() -> None:
    """Segunda trava do ADR-0033: mesmo com `review_status == 'approved'` via
    aprovação humana com justificativa (que não passa pela auto-resolução), um
    comentário obrigatório pendente de uma rodada anterior ainda bloqueia o merge."""
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    reprovado = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        comentarios=[ReviewCommentDraft(arquivo="a.py", linha=7, descricao="x", obrigatorio=True)],
    )
    _aplicar(svc, orch_id, pr_id, reprovado)

    svc.report_ci(orch_id, pr_id, "passed")
    svc.report_review(orch_id, pr_id, "approved", justificativa="urgência aprovada por humano")

    pr = svc.list_pulls(orch_id)[0]
    assert pr.review_status == "approved"
    with pytest.raises(ValueError, match="a.py:7"):
        svc.merge_pr(orch_id, pr_id)


# ------------------------------------------------------------- resolução manual


def test_resolve_review_comment_marca_resolvido_e_actor() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    verdito = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        comentarios=[ReviewCommentDraft(arquivo="a.py", descricao="x", obrigatorio=True)],
    )
    _aplicar(svc, orch_id, pr_id, verdito)
    comentario = svc.list_review_comments(orch_id, pr_id)[0]

    resolvido = svc.resolve_review_comment(orch_id, pr_id, comentario.id, actor="operador")
    assert resolvido.status == "resolvido"
    assert resolvido.resolved_by == "operador"
    assert resolvido.resolved_at is not None


def test_resolve_review_comment_ja_resolvido_recusa() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    verdito = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        comentarios=[ReviewCommentDraft(arquivo="a.py", descricao="x", obrigatorio=True)],
    )
    _aplicar(svc, orch_id, pr_id, verdito)
    comentario = svc.list_review_comments(orch_id, pr_id)[0]
    svc.resolve_review_comment(orch_id, pr_id, comentario.id)
    with pytest.raises(ValueError, match="já resolvido"):
        svc.resolve_review_comment(orch_id, pr_id, comentario.id)


def test_resolve_review_comment_inexistente_leva_a_keyerror() -> None:
    svc = OrchestrationService()
    orch_id, pr_id = _orch_com_pr(svc)
    with pytest.raises(KeyError):
        svc.resolve_review_comment(orch_id, pr_id, "comment_inexistente")


# ---------------------------------------------------------------------- listagem


def test_list_review_comments_filtra_por_pr() -> None:
    svc = OrchestrationService()
    orch_id1, pr1_id = _orch_com_pr(svc)
    orch_id2, pr2_id = _orch_com_pr(svc)
    _aplicar(
        svc,
        orch_id1,
        pr1_id,
        ReviewVerdict(
            veredito="alteracoes_obrigatorias",
            comentarios=[ReviewCommentDraft(arquivo="a.py", descricao="x")],
        ),
    )
    assert len(svc.list_review_comments(orch_id1, pr1_id)) == 1
    assert svc.list_review_comments(orch_id2, pr2_id) == []
