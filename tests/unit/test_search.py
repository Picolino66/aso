"""Busca global de texto livre (wf §2.3) — ADR-0035."""

from __future__ import annotations

from aso.control.search import SearchItem, buscar

_ITENS = [
    SearchItem(tipo="demanda", titulo="Implementar cálculo de frete", orchestration_id="o1"),
    SearchItem(
        tipo="card", titulo="Ajustar validação de frete", orchestration_id="o1", card_id="c1"
    ),
    SearchItem(
        tipo="documento",
        titulo="ADR-0001 — Frete internacional",
        orchestration_id="o1",
        adr_id="ADR-0001",
    ),
    SearchItem(tipo="demanda", titulo="Corrigir login OAuth", orchestration_id="o2"),
]


def test_busca_case_insensitive_no_titulo() -> None:
    resultado = buscar("FRETE", _ITENS)
    assert len(resultado) == 3
    assert {r.tipo for r in resultado} == {"demanda", "card", "documento"}


def test_busca_sem_correspondencia_devolve_vazio() -> None:
    assert buscar("inexistente", _ITENS) == []


def test_busca_com_query_vazia_devolve_vazio() -> None:
    assert buscar("", _ITENS) == []
    assert buscar("   ", _ITENS) == []


def test_busca_respeita_limite() -> None:
    muitos = [
        SearchItem(tipo="card", titulo=f"card frete {i}", orchestration_id="o1") for i in range(50)
    ]
    resultado = buscar("frete", muitos, limite=5)
    assert len(resultado) == 5
