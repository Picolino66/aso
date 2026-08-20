"""Ciclo de correção (§15, ADR-0017): revisão reprovada vira ação objetiva no card.

`_apply_review_verdict` é o núcleo que traduz um veredito em `review_status` +
movimentação de card; testado diretamente (como já se faz com `_bundle`/`_build_task`
em outros arquivos) porque simular o veredito através de `run_review` exigiria um
workspace git real só para obter o diff — irrelevante para esta regra.
"""

from __future__ import annotations

from aso.control.orchestration_service import OrchestrationService
from aso.control.review import ReviewAction, ReviewVerdict
from aso.shared.types import ColumnKey


def _orch_com_pr_e_card(svc: OrchestrationService) -> tuple[str, str, str]:
    orch = svc.create_orchestration("implementar cálculo de frete")
    card = svc.get_cards(orch.id)[0]
    card.executor = "codex-gpt-5-high"
    pr = svc.open_pr(orch.id, card.id, branch="feat/frete-abc123")
    return orch.id, pr.id, card.id


def test_alteracoes_obrigatorias_move_card_para_needs_fix_com_acoes() -> None:
    svc = OrchestrationService()
    orch_id, pr_id, card_id = _orch_com_pr_e_card(svc)
    b = svc._bundle(orch_id)  # noqa: SLF001
    pr = svc._find_pr(b, pr_id)  # noqa: SLF001
    card = b.board_service.get_card(card_id)
    verdito = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        resumo="faltam testes",
        acoes=[
            ReviewAction(descricao="Adicionar teste de frete negativo", severidade="obrigatoria"),
            ReviewAction(descricao="Renomear variável x", severidade="sugestao"),
        ],
        revisor="codex-gpt-5-medium",
        origem="agente",
    )

    resultado = svc._apply_review_verdict(b, pr, card, verdito, actor="operador")  # noqa: SLF001

    assert resultado.review_status == "changes_requested"
    assert resultado.review_rounds == 1
    card_atualizado = svc.get_cards(orch_id)[0]
    assert card_atualizado.status == ColumnKey.NEEDS_FIX
    # Só a ação obrigatória chega ao card — a sugestão fica só no veredito.
    assert card_atualizado.correction_actions == ["Adicionar teste de frete negativo"]


def test_build_task_leva_correction_actions_ao_agente() -> None:
    svc = OrchestrationService()
    orch_id, _pr_id, card_id = _orch_com_pr_e_card(svc)
    b = svc._bundle(orch_id)  # noqa: SLF001
    card = b.board_service.get_card(card_id)
    card.correction_actions = ["Adicionar teste de frete negativo"]
    agent = b.agent_registry.get(card.assignee)

    task = svc._build_task(b, card, agent)  # noqa: SLF001

    assert task["content"]["correction_actions"] == ["Adicionar teste de frete negativo"]


def test_aprovacao_posterior_limpa_correction_actions() -> None:
    svc = OrchestrationService()
    orch_id, pr_id, card_id = _orch_com_pr_e_card(svc)
    b = svc._bundle(orch_id)  # noqa: SLF001
    card = b.board_service.get_card(card_id)
    card.correction_actions = ["Ação pendente de uma rodada anterior"]

    svc.report_review(orch_id, pr_id, "approved", justificativa="revisado manualmente")

    card_atualizado = svc.get_cards(orch_id)[0]
    assert card_atualizado.correction_actions == []


def test_reprovado_com_so_comentarios_antigos_resolvidos_ainda_usa_acoes_do_veredito() -> None:
    """Bug real (code-review ultra): o fallback para `verdito.acoes` só disparava
    quando a PR nunca tinha comentário nenhum (`if comentarios_da_pr:`) — uma PR
    com comentários de uma rodada ANTERIOR já resolvidos faz `comentarios_da_pr`
    não-vazio, mas o filtro `obrigatorio and pendente` dá `[]`, e o veredito atual
    (com ações obrigatórias reais) era descartado, deixando NeedsFix sem
    orientação nenhuma."""
    svc = OrchestrationService()
    orch_id, pr_id, card_id = _orch_com_pr_e_card(svc)
    b = svc._bundle(orch_id)  # noqa: SLF001
    pr = svc._find_pr(b, pr_id)  # noqa: SLF001
    card = b.board_service.get_card(card_id)
    # Rodada anterior: veredito aprovado resolveu o único comentário que existia.
    primeiro_veredito = ReviewVerdict(
        veredito="aprovado_com_sugestoes",
        resumo="ok com ressalva",
        comentarios=[],
        revisor="codex-gpt-5-medium",
        origem="agente",
    )
    svc._apply_review_verdict(b, pr, card, primeiro_veredito, actor="operador")  # noqa: SLF001

    # Nova rodada: reprovado, com ações obrigatórias reais, mas SEM comentário
    # novo nesta rodada — `comentarios_da_pr` continua vazio (não houve comentário
    # em nenhuma rodada aqui), então este teste cobre exatamente o `else` original.
    segundo_veredito = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        resumo="quebrou o teste X",
        acoes=[ReviewAction(descricao="Corrigir teste X", severidade="obrigatoria")],
        revisor="codex-gpt-5-medium",
        origem="agente",
    )

    resultado = svc._apply_review_verdict(  # noqa: SLF001
        b, pr, card, segundo_veredito, actor="operador"
    )

    assert resultado.review_status == "changes_requested"
    card_atualizado = svc.get_cards(orch_id)[0]
    assert card_atualizado.correction_actions == ["Corrigir teste X"]


def test_reprovado_com_comentario_antigo_resolvido_e_sem_comentario_novo_usa_veredito() -> None:
    """Mesmo bug, cenário em que `comentarios_da_pr` FICA não-vazio (comentário de
    rodada anterior, já resolvido) — este é o caso que a condição antiga
    (`if comentarios_da_pr:`) tratava errado, pegando o ramo do filtro (que dá
    `[]`) em vez do fallback."""
    svc = OrchestrationService()
    orch_id, pr_id, card_id = _orch_com_pr_e_card(svc)
    b = svc._bundle(orch_id)  # noqa: SLF001
    pr = svc._find_pr(b, pr_id)  # noqa: SLF001
    card = b.board_service.get_card(card_id)
    primeiro_veredito = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        resumo="ajuste de nome",
        acoes=[ReviewAction(descricao="Renomear variável", severidade="obrigatoria")],
        revisor="codex-gpt-5-medium",
        origem="agente",
    )
    svc._apply_review_verdict(b, pr, card, primeiro_veredito, actor="operador")  # noqa: SLF001
    # Resolve manualmente o comentário obrigatório da rodada 1 (fluxo real: o
    # agente corrigiu, e alguém marcou o comentário como resolvido).
    for c in b.review_comments:
        if c.pr_id == pr.id:
            c.status = "resolvido"

    segundo_veredito = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        resumo="quebrou outro teste",
        acoes=[ReviewAction(descricao="Corrigir teste Y", severidade="obrigatoria")],
        comentarios=[],  # nenhum comentário NOVO nesta rodada
        revisor="codex-gpt-5-medium",
        origem="agente",
    )

    resultado = svc._apply_review_verdict(  # noqa: SLF001
        b, pr, card, segundo_veredito, actor="operador"
    )

    assert resultado.review_status == "changes_requested"
    card_atualizado = svc.get_cards(orch_id)[0]
    assert card_atualizado.correction_actions == ["Corrigir teste Y"]


def test_aprovado_mas_risco_exige_humano_nao_move_para_needs_fix() -> None:
    """Veredito aprovado que fica `pending` (risco alto) não é reprovação — o card
    não deve ir para `NeedsFix`."""
    svc = OrchestrationService()
    orch_id, pr_id, card_id = _orch_com_pr_e_card(svc)
    b = svc._bundle(orch_id)  # noqa: SLF001
    pr = svc._find_pr(b, pr_id)  # noqa: SLF001
    card = b.board_service.get_card(card_id)
    # Ficha de risco alto (§4.3): aprovação do agente não fecha sozinha.
    b.orchestration.demand_brief = {"risco": "high"}
    verdito = ReviewVerdict(veredito="aprovado", revisor="outro-executor", origem="agente")

    resultado = svc._apply_review_verdict(b, pr, card, verdito, actor="operador")  # noqa: SLF001

    assert resultado.review_status == "pending"
    card_atualizado = svc.get_cards(orch_id)[0]
    assert card_atualizado.status != ColumnKey.NEEDS_FIX
