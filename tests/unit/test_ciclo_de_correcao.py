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
