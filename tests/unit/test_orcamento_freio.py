"""Freio de orçamento no roteamento de falha (§1.2/§3.2 do plano7.md) — ADR-0026.

`_route_failure` é o ponto único que junta a política pura de `control/failure.py`
com o orçamento — testado diretamente (mesmo padrão de `test_ciclo_de_correcao.py`),
porque simular via `run_card` exigiria um provider CLI real só para produzir o erro.
"""

from __future__ import annotations

from aso.agents.executor import AgentExecutionError
from aso.control.failure import ACAO_ESCALAR_HUMANO, ACAO_MESMO_AGENTE
from aso.control.orchestration_service import OrchestrationService
from aso.shared.types import ColumnKey


def _orch_com_card(svc: OrchestrationService) -> tuple[str, str]:
    orch = svc.create_orchestration("implementar cálculo de frete")
    card = svc.get_cards(orch.id)[0]
    return orch.id, card.id


def test_orcamento_estourado_transforma_aumentar_effort_em_escalar_humano() -> None:
    svc = OrchestrationService()
    orch_id, card_id = _orch_com_card(svc)
    b = svc._bundle(orch_id)  # noqa: SLF001
    b.orchestration.orcamento_usd = 1.0
    card = b.board_service.get_card(card_id)
    assert card is not None
    card.uso = {"custo_usd": 5.0, "execucoes": 1, "execucoes_sem_custo": 0}  # já estourou

    # DIAG_TIMEOUT na 1ª tentativa normalmente vira `aumentar_effort` (ver
    # test_failure_routing.py) — com orçamento estourado, o freio intercepta.
    decisao = svc._route_failure(  # noqa: SLF001
        b,
        card,
        AgentExecutionError("Executor CLI não terminou em 1800s e foi encerrado."),
        executor_atual="claude-code",
        effort_atual="low",
    )

    assert decisao.acao == ACAO_ESCALAR_HUMANO
    assert "orçamento" in decisao.motivo
    atualizado = svc.get_cards(orch_id)[0]
    assert atualizado.status == ColumnKey.FAILED


def test_sem_orcamento_configurado_escalada_normal_continua() -> None:
    """Regressão: sem teto (comportamento anterior a este incremento), a política
    de effort segue intocada."""
    svc = OrchestrationService()
    orch_id, card_id = _orch_com_card(svc)
    b = svc._bundle(orch_id)  # noqa: SLF001
    card = b.board_service.get_card(card_id)
    assert card is not None
    card.uso = {"custo_usd": 999.0, "execucoes": 1, "execucoes_sem_custo": 0}

    decisao = svc._route_failure(  # noqa: SLF001
        b,
        card,
        AgentExecutionError("Executor CLI não terminou em 1800s e foi encerrado."),
        executor_atual="claude-code",
        effort_atual="low",
    )

    assert decisao.acao != ACAO_ESCALAR_HUMANO or "orçamento" not in decisao.motivo


def test_orcamento_estourado_recusa_run_card_mas_nao_a_execucao_em_curso() -> None:
    """`run_card`/`race_card` recusam execução NOVA quando o teto já estourou —
    não há como matar "a que está rodando" num serviço síncrono, então a garantia
    testável é: a chamada nem começa."""
    svc = OrchestrationService()
    orch_id, card_id = _orch_com_card(svc)
    b = svc._bundle(orch_id)  # noqa: SLF001
    b.orchestration.orcamento_usd = 1.0
    card = b.board_service.get_card(card_id)
    assert card is not None
    card.uso = {"custo_usd": 5.0, "execucoes": 1, "execucoes_sem_custo": 0}
    card.assignee = "BackendDevelopmentAgent"

    try:
        svc.run_card(orch_id, card_id)
    except ValueError as exc:
        assert "rçamento" in str(exc)
    else:
        raise AssertionError("run_card deveria recusar com orçamento estourado")


def test_mesmo_agente_nao_e_afetado_pelo_freio() -> None:
    """O freio só intercepta `aumentar_effort`/`trocar_executor` (que gastam mais) —
    `mesmo_agente` (retry sem custo extra de perfil) não deveria virar escalar."""
    svc = OrchestrationService()
    orch_id, card_id = _orch_com_card(svc)
    b = svc._bundle(orch_id)  # noqa: SLF001
    b.orchestration.orcamento_usd = 1.0
    card = b.board_service.get_card(card_id)
    assert card is not None
    card.uso = {"custo_usd": 5.0, "execucoes": 1, "execucoes_sem_custo": 0}

    # DIAG_DESCONHECIDO na 1ª tentativa é `mesmo_agente` (ver test_failure_routing.py).
    decisao = svc._route_failure(  # noqa: SLF001
        b,
        card,
        AgentExecutionError("algo inesperado aconteceu"),
        executor_atual="",
        effort_atual="",
    )

    assert decisao.acao == ACAO_MESMO_AGENTE
