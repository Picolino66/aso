"""Checklist de preparação para implementação (§10 do fluxo.md, wf §16) — ADR-0030."""

from __future__ import annotations

import pytest

from aso.control.preparation import (
    ITEM_BRANCH_CRIADA,
    ITEM_CARD_DESBLOQUEADO,
    ITEM_CODIGO_AFETADO_ANALISADO,
    ITEM_CRITERIOS_ANALISADOS,
    ITEM_DEPENDENCIAS_VERIFICADAS,
    ITEM_ESPECIFICACAO_LIDA,
    ITEM_PLANO_REGISTRADO,
    ITEM_TESTES_EXISTENTES_IDENTIFICADOS,
    ITENS_CHECKLIST_PREPARACAO,
    PreparationChecklistError,
    checklist_completo,
    marcar_item,
)


def test_itens_do_checklist_sao_exatamente_os_oito_do_10() -> None:
    assert len(ITENS_CHECKLIST_PREPARACAO) == 8
    assert ITENS_CHECKLIST_PREPARACAO == (
        ITEM_ESPECIFICACAO_LIDA,
        ITEM_CRITERIOS_ANALISADOS,
        ITEM_CODIGO_AFETADO_ANALISADO,
        ITEM_DEPENDENCIAS_VERIFICADAS,
        ITEM_TESTES_EXISTENTES_IDENTIFICADOS,
        ITEM_BRANCH_CRIADA,
        ITEM_PLANO_REGISTRADO,
        ITEM_CARD_DESBLOQUEADO,
    )


def test_marcar_item_adiciona_com_autor_e_timestamp() -> None:
    checklist = marcar_item([], ITEM_ESPECIFICACAO_LIDA, autor="sistema")
    assert len(checklist) == 1
    item = checklist[0]
    assert item["item"] == ITEM_ESPECIFICACAO_LIDA
    assert item["concluido"] is True
    assert item["autor"] == "sistema"
    assert item["at"]


def test_marcar_item_fora_do_vocabulario_recusa() -> None:
    with pytest.raises(PreparationChecklistError):
        marcar_item([], "item inventado", autor="sistema")


def test_marcar_item_repetido_atualiza_em_vez_de_duplicar() -> None:
    checklist = marcar_item([], ITEM_BRANCH_CRIADA, autor="sistema")
    checklist = marcar_item(checklist, ITEM_BRANCH_CRIADA, autor="sistema")
    assert len(checklist) == 1


def test_marcar_item_preserva_outros_itens_ja_marcados() -> None:
    checklist = marcar_item([], ITEM_ESPECIFICACAO_LIDA, autor="sistema")
    checklist = marcar_item(checklist, ITEM_BRANCH_CRIADA, autor="sistema")
    assert {c["item"] for c in checklist} == {ITEM_ESPECIFICACAO_LIDA, ITEM_BRANCH_CRIADA}


def test_marcar_item_pode_desmarcar() -> None:
    checklist = marcar_item([], ITEM_BRANCH_CRIADA, autor="sistema")
    checklist = marcar_item(checklist, ITEM_BRANCH_CRIADA, autor="sistema", concluido=False)
    assert checklist[0]["concluido"] is False


def test_checklist_completo_falso_quando_vazio() -> None:
    assert checklist_completo([]) is False


def test_checklist_completo_falso_com_item_faltando() -> None:
    checklist: list[dict[str, object]] = []
    for item in ITENS_CHECKLIST_PREPARACAO[:-1]:
        checklist = marcar_item(checklist, item, autor="sistema")
    assert checklist_completo(checklist) is False


def test_checklist_completo_falso_se_algum_item_desmarcado() -> None:
    checklist: list[dict[str, object]] = []
    for item in ITENS_CHECKLIST_PREPARACAO:
        checklist = marcar_item(checklist, item, autor="sistema")
    checklist = marcar_item(checklist, ITENS_CHECKLIST_PREPARACAO[0], concluido=False)
    assert checklist_completo(checklist) is False


def test_checklist_completo_verdadeiro_com_os_oito_marcados() -> None:
    checklist: list[dict[str, object]] = []
    for item in ITENS_CHECKLIST_PREPARACAO:
        checklist = marcar_item(checklist, item, autor="sistema")
    assert checklist_completo(checklist) is True
