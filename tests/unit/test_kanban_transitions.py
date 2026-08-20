"""Máquina de estados do card (Tela 11, wf §35) — ADR-0047."""

from __future__ import annotations

from aso.kanban.transitions import (
    ROTULOS_WIREFRAME,
    TRANSICOES_VALIDAS,
    motivo_transicao_invalida,
    transicao_valida,
)
from aso.shared.types import ColumnKey


def test_transicao_para_a_mesma_coluna_e_sempre_valida() -> None:
    for coluna in ColumnKey:
        assert transicao_valida(coluna, coluna) is True


def test_transicoes_do_wireframe_sao_validas() -> None:
    assert transicao_valida(ColumnKey.BACKLOG, ColumnKey.PLANNING) is True
    assert transicao_valida(ColumnKey.PLANNING, ColumnKey.WAITING_HUMAN) is True
    assert transicao_valida(ColumnKey.WAITING_HUMAN, ColumnKey.READY) is True
    assert transicao_valida(ColumnKey.WAITING_HUMAN, ColumnKey.PLANNING) is True  # reprovado
    assert transicao_valida(ColumnKey.READY, ColumnKey.IN_PROGRESS) is True
    assert transicao_valida(ColumnKey.IN_PROGRESS, ColumnKey.TESTING) is True
    assert transicao_valida(ColumnKey.IN_PROGRESS, ColumnKey.BLOCKED) is True
    assert transicao_valida(ColumnKey.BLOCKED, ColumnKey.READY) is True  # dependência resolvida
    assert transicao_valida(ColumnKey.TESTING, ColumnKey.REVIEW) is True
    assert transicao_valida(ColumnKey.TESTING, ColumnKey.NEEDS_FIX) is True
    assert transicao_valida(ColumnKey.REVIEW, ColumnKey.DEPLOYING) is True
    assert transicao_valida(ColumnKey.REVIEW, ColumnKey.NEEDS_FIX) is True
    assert transicao_valida(ColumnKey.NEEDS_FIX, ColumnKey.IN_PROGRESS) is True
    assert transicao_valida(ColumnKey.DEPLOYING, ColumnKey.VALIDATING) is True
    assert transicao_valida(ColumnKey.DEPLOYING, ColumnKey.NEEDS_FIX) is True
    assert transicao_valida(ColumnKey.VALIDATING, ColumnKey.DONE) is True
    assert transicao_valida(ColumnKey.VALIDATING, ColumnKey.NEEDS_FIX) is True


def test_transicoes_terminais_nao_tem_saida() -> None:
    assert TRANSICOES_VALIDAS[ColumnKey.DONE] == frozenset()
    assert TRANSICOES_VALIDAS[ColumnKey.CANCELLED] == frozenset()


def test_colunas_sem_uso_real_nao_tem_transicao_manual() -> None:
    for coluna in (ColumnKey.WAITING_AGENT, ColumnKey.FAILED, ColumnKey.ARCHIVED):
        assert TRANSICOES_VALIDAS[coluna] == frozenset()
        assert transicao_valida(ColumnKey.BACKLOG, coluna) is False


def test_transicao_que_pula_etapas_e_invalida() -> None:
    assert transicao_valida(ColumnKey.BACKLOG, ColumnKey.DONE) is False
    assert transicao_valida(ColumnKey.BACKLOG, ColumnKey.IN_PROGRESS) is False


def test_motivo_transicao_invalida_lista_alternativas() -> None:
    motivo = motivo_transicao_invalida(ColumnKey.BACKLOG, ColumnKey.DONE)
    assert "Backlog" in motivo
    assert "Done" in motivo
    assert "Planning" in motivo or "Cancelled" in motivo


def test_motivo_transicao_invalida_estado_terminal() -> None:
    motivo = motivo_transicao_invalida(ColumnKey.DONE, ColumnKey.BACKLOG)
    assert "terminal" in motivo


def test_rotulos_wireframe_cobrem_as_14_colunas_do_wf() -> None:
    assert len(ROTULOS_WIREFRAME) == 13  # 14 do wf, com "Pronto p/ implantação" colapsado
    assert ROTULOS_WIREFRAME[ColumnKey.BACKLOG] == "Backlog"
    assert ColumnKey.WAITING_AGENT not in ROTULOS_WIREFRAME
