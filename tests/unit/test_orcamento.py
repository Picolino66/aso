"""Orçamento com freio (§1.2/§3.2 do plano7.md) — ADR-0026."""

from __future__ import annotations

from aso.control.orcamento import (
    SITUACAO_ALERTA,
    SITUACAO_ESTOURADO,
    SITUACAO_OK,
    avaliar_orcamento,
)


def test_sem_teto_configurado_e_sempre_ok() -> None:
    situacao, motivo = avaliar_orcamento(999.0, None)
    assert situacao == SITUACAO_OK
    assert "sem teto" in motivo


def test_teto_zero_ou_negativo_e_tratado_como_sem_teto() -> None:
    assert avaliar_orcamento(50.0, 0.0)[0] == SITUACAO_OK
    assert avaliar_orcamento(50.0, -10.0)[0] == SITUACAO_OK


def test_abaixo_de_80_por_cento_e_ok() -> None:
    situacao, _ = avaliar_orcamento(50.0, 100.0)
    assert situacao == SITUACAO_OK


def test_a_partir_de_80_por_cento_e_alerta() -> None:
    situacao, motivo = avaliar_orcamento(80.0, 100.0)
    assert situacao == SITUACAO_ALERTA
    assert "80" in motivo or "0.8" in motivo or "%" in motivo


def test_no_teto_ou_acima_e_estourado() -> None:
    assert avaliar_orcamento(100.0, 100.0)[0] == SITUACAO_ESTOURADO
    assert avaliar_orcamento(150.0, 100.0)[0] == SITUACAO_ESTOURADO
