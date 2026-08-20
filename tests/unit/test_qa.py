"""QA humano — regra de exigência e diagnóstico de reprovação (§16/§17, ADR-0025).

`exige_qa_manual` é pura (mesmo molde de `exige_confirmacao_humana`,
ADR-0017): uma matriz cobre domínio × complexidade × tipo de card. O
diagnóstico de reprovação reaproveita `diagnosticar`/`decidir` de
`control/failure.py` — sem taxonomia nova (§17).
"""

from __future__ import annotations

import pytest

from aso.control.failure import DIAG_FALHA_DE_QA, FailureRecord, decidir, diagnosticar
from aso.control.orchestration_service import OrchestrationService
from aso.control.qa import exige_qa_manual
from aso.control.triage import DemandBrief
from aso.kanban.models import KanbanCard
from aso.shared.types import CardType, ColumnKey, Phase


def _card(tipo: CardType = CardType.TASK) -> KanbanCard:
    return KanbanCard(
        board_id="board_qa",
        orchestration_id="orch_qa",
        phase=Phase.F5,
        type=tipo,
        title="card",
        status=ColumnKey.TESTING,
    )


@pytest.mark.parametrize(
    ("dominios", "complexidade", "tipo", "esperado"),
    [
        ([], "intermediaria", CardType.TASK, False),
        (["frontend"], "intermediaria", CardType.TASK, True),
        (["backend"], "intermediaria", CardType.TASK, False),
        ([], "complexa", CardType.TASK, True),
        ([], "estrategica", CardType.TASK, True),
        ([], "simples", CardType.TASK, False),
        ([], "intermediaria", CardType.EPIC, True),
        ([], "intermediaria", CardType.FEATURE, True),
        ([], "intermediaria", CardType.BUG, False),
    ],
)
def test_exige_qa_manual_matriz(
    dominios: list[str], complexidade: str, tipo: CardType, esperado: bool
) -> None:
    brief = DemandBrief(dominios=dominios, complexidade=complexidade)
    assert exige_qa_manual(brief, _card(tipo)) is esperado


def test_diagnostico_falha_de_qa_via_categoria() -> None:
    record = FailureRecord(mensagem="QA reprovou: botão não responde", categoria="qa")
    assert diagnosticar(record) == DIAG_FALHA_DE_QA


def test_falha_de_qa_escala_mesmo_agente_depois_effort_depois_humano() -> None:
    decisao1 = decidir(DIAG_FALHA_DE_QA, tentativa=1)
    assert decisao1.acao == "mesmo_agente"
    decisao2 = decidir(DIAG_FALHA_DE_QA, tentativa=2, executor_atual="x", effort_atual="low")
    assert decisao2.acao == "aumentar_effort"
    assert decisao2.effort == "medium"
    decisao3 = decidir(DIAG_FALHA_DE_QA, tentativa=3)
    assert decisao3.acao == "escalar_humano"


# ------------------------------------------------------- OrchestrationService (§16/§17)


def test_register_qa_check_entra_no_ring_do_card() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    check = svc.register_qa_check(orch.id, card.id, cenario="login com SSO")
    assert check.cenario == "login com SSO"
    assert check.status == "pendente"
    checks = svc.get_qa_checks(orch.id, card.id)
    assert len(checks) == 1 and checks[0].cenario == "login com SSO"


def test_register_qa_check_ring_limitado_a_dez() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    for i in range(12):
        svc.register_qa_check(orch.id, card.id, cenario=f"cenario {i}")
    checks = svc.get_qa_checks(orch.id, card.id)
    assert len(checks) == 10
    assert checks[0].cenario == "cenario 2"
    assert checks[-1].cenario == "cenario 11"


def test_fail_qa_check_cria_bug_vinculado_ao_card_original() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    svc.register_qa_check(
        orch.id,
        card.id,
        cenario="checkout com cupom",
        passos=["abrir carrinho", "aplicar cupom X"],
        resultado_esperado="desconto aplicado",
        gravidade="alta",
    )

    atualizado = svc.fail_qa_check(
        orch.id, card.id, 0, resultado_obtido="cupom não aplicou desconto"
    )

    assert atualizado.status.value in ("NeedsFix", "Failed")
    checks = svc.get_qa_checks(orch.id, card.id)
    assert checks[0].status == "falhou"
    assert checks[0].resultado_obtido == "cupom não aplicou desconto"

    cards = svc.get_cards(orch.id)
    bug = next(c for c in cards if c.type == CardType.BUG)
    assert bug.parent_id == card.id
    assert bug.dependencies == [card.id]
    assert bug.priority.value == "high"
    assert "checkout com cupom" in bug.title
    assert "abrir carrinho" in bug.description
    assert "desconto aplicado" in bug.description
    assert "cupom não aplicou desconto" in bug.description

    # A falha entra no ring do card original, reaproveitando o roteamento §13/ADR-0019.
    assert card.failures
    assert card.failures[-1]["categoria"] == "qa"


def test_fail_qa_check_indice_invalido_leva_a_erro() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    with pytest.raises(KeyError):
        svc.fail_qa_check(orch.id, card.id, 0)


def test_register_qa_check_gera_codigo_e_aceita_titulo_pre_condicoes() -> None:
    """Plano de teste manual (Tela 20, wf §22.1, ADR-0049)."""
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    check = svc.register_qa_check(
        orch.id,
        card.id,
        cenario="login com SSO",
        titulo="Login via SSO corporativo",
        pre_condicoes="usuário com conta SSO ativa",
    )
    assert check.codigo  # gerado, nunca um "QA-001" fabricado
    assert check.titulo == "Login via SSO corporativo"
    assert check.pre_condicoes == "usuário com conta SSO ativa"


def test_fail_qa_check_repetido_escala_para_humano_e_falha_apos_limite() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    for _ in range(4):
        svc.register_qa_check(orch.id, card.id, cenario="mesmo cenario")
        idx = len(svc.get_qa_checks(orch.id, card.id)) - 1
        atualizado = svc.fail_qa_check(orch.id, card.id, idx)
    # Depois de esgotar as tentativas automáticas (padrão: 3), escala para Failed.
    assert atualizado.status.value == "Failed"
