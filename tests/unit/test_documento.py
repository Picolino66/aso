"""Documento — os 8 tipos sem representação anterior (Tela 08, wf §10) — ADR-0046."""

from __future__ import annotations

from aso.control.documento import (
    ROTULOS,
    TIPOS_DA_ESPECIFICACAO,
    TIPOS_VALIDOS,
    DocumentComment,
    Documento,
    diff_versoes,
)


def test_tipos_validos_tem_oito_itens() -> None:
    assert len(TIPOS_VALIDOS) == 8
    assert set(ROTULOS) == TIPOS_VALIDOS


def test_tipos_da_especificacao_nao_se_sobrepoem_aos_oito_novos() -> None:
    assert not (TIPOS_VALIDOS & set(TIPOS_DA_ESPECIFICACAO))
    assert len(TIPOS_DA_ESPECIFICACAO) == 5


def test_documento_default_status_rascunho() -> None:
    assert Documento().status == "rascunho"


def test_document_comment_default_status_pendente() -> None:
    assert DocumentComment(descricao="x").status == "pendente"


def test_diff_versoes_sem_mudanca_e_vazio() -> None:
    assert diff_versoes("# título\ntexto", "# título\ntexto") == []


def test_diff_versoes_detecta_linha_alterada() -> None:
    diff = diff_versoes("linha 1\nlinha 2\n", "linha 1\nlinha 2 mudou\n")
    texto = "\n".join(diff)
    assert "-linha 2" in texto
    assert "+linha 2 mudou" in texto


def test_diff_versoes_detecta_linha_adicionada() -> None:
    diff = diff_versoes("linha 1\n", "linha 1\nlinha 2\n")
    texto = "\n".join(diff)
    assert "+linha 2" in texto
