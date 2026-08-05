"""Diagnóstico preciso a partir da categoria da verificação (§4.3, ADR-0022).

Com `categoria` preenchida, `diagnosticar` mapeia direto — fato, não palpite por
palavra-chave. Sem categoria (registros legados de execução, não de gate), cai na
heurística de sempre — nenhuma orquestração existente muda de comportamento.
"""

from __future__ import annotations

from aso.control.failure import (
    ACAO_ESCALAR_HUMANO,
    ACAO_MESMO_AGENTE,
    DIAG_FALHA_TRIVIAL,
    DIAG_RISCO_ALTO,
    DIAG_TESTE_FALHOU,
    FailureRecord,
    decidir,
    diagnosticar,
)


def test_categoria_lint_e_falha_trivial_sem_consultar_palavras_chave() -> None:
    # Mensagem não contém nenhuma palavra-chave conhecida — só a categoria decide.
    record = FailureRecord(check="lint", categoria="lint", mensagem="nada reconhecível")
    assert diagnosticar(record) == DIAG_FALHA_TRIVIAL


def test_categoria_formatacao_e_falha_trivial() -> None:
    record = FailureRecord(check="formatacao", categoria="formatacao")
    assert diagnosticar(record) == DIAG_FALHA_TRIVIAL


def test_categoria_testes_e_teste_falhou() -> None:
    record = FailureRecord(check="testes", categoria="testes", mensagem="sem pista nenhuma")
    assert diagnosticar(record) == DIAG_TESTE_FALHOU


def test_categoria_seguranca_e_risco_alto() -> None:
    record = FailureRecord(check="bandit", categoria="seguranca")
    assert diagnosticar(record) == DIAG_RISCO_ALTO


def test_categoria_dependencias_e_risco_alto() -> None:
    record = FailureRecord(check="pip-audit", categoria="dependencias")
    assert diagnosticar(record) == DIAG_RISCO_ALTO


def test_sem_categoria_cai_na_heuristica_de_sempre() -> None:
    """Registro legado (execução, não gate nomeado) — comportamento inalterado."""
    record = FailureRecord(
        mensagem="AssertionError: 1 != 2", saida="Traceback (most recent call last):"
    )
    assert diagnosticar(record) == DIAG_TESTE_FALHOU


def test_categoria_desconhecida_cai_na_heuristica() -> None:
    """Categoria fora do vocabulário mapeado não quebra — heurística assume."""
    record = FailureRecord(categoria="inexistente", mensagem="algo inesperado aconteceu")
    from aso.control.failure import DIAG_DESCONHECIDO

    assert diagnosticar(record) == DIAG_DESCONHECIDO


def test_falha_trivial_nao_sobe_effort_na_primeira_tentativa() -> None:
    decisao = decidir(DIAG_FALHA_TRIVIAL, 1, executor_atual="a", effort_atual="low")
    assert decisao.acao == ACAO_MESMO_AGENTE
    assert decisao.effort is None


def test_falha_trivial_escala_na_terceira_tentativa() -> None:
    decisao = decidir(DIAG_FALHA_TRIVIAL, 3, executor_atual="a", effort_atual="low")
    assert decisao.acao == ACAO_ESCALAR_HUMANO


def test_risco_alto_escala_ja_na_primeira_falha() -> None:
    decisao = decidir(DIAG_RISCO_ALTO, 1, executor_atual="a", effort_atual="low")
    assert decisao.acao == ACAO_ESCALAR_HUMANO
