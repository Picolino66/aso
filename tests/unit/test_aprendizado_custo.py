"""Custo real no relatório de aprendizado (§1.1/§1.3 do plano7.md) — ADR-0026."""

from __future__ import annotations

from aso.observability.aprendizado import CardSnapshot, consolidar


def test_custo_por_entrega_divide_pelas_entregas_nao_pelo_total() -> None:
    cards = [
        CardSnapshot(
            id="c1", executor="claude", custo_usd=1.0, uso_indisponivel=False, entregue=True
        ),
        CardSnapshot(
            id="c2", executor="claude", custo_usd=2.0, uso_indisponivel=False, entregue=True
        ),
        CardSnapshot(
            id="c3", executor="claude", custo_usd=3.0, uso_indisponivel=False, entregue=False
        ),
    ]
    rel = consolidar("orch", cards, [])
    d = rel.desempenho_por_executor[0]
    assert d.custo_total_usd == 6.0
    assert d.custo_por_entrega == 3.0  # 6.0 / 2 entregas, não / 3 cards


def test_zero_entregas_nao_divide_por_zero() -> None:
    cards = [CardSnapshot(id="c1", executor="claude", custo_usd=5.0, entregue=False)]
    rel = consolidar("orch", cards, [])
    d = rel.desempenho_por_executor[0]
    assert d.custo_total_usd == 5.0
    assert d.custo_por_entrega == 0.0


def test_execucoes_sem_custo_aparecem_contadas_nao_somadas_como_zero() -> None:
    cards = [
        CardSnapshot(
            id="c1", executor="codex", custo_usd=0.0, uso_indisponivel=True, entregue=True
        ),
        CardSnapshot(
            id="c2", executor="codex", custo_usd=4.0, uso_indisponivel=False, entregue=True
        ),
    ]
    rel = consolidar("orch", cards, [])
    d = rel.desempenho_por_executor[0]
    assert d.execucoes_sem_custo == 1
    assert d.custo_total_usd == 4.0  # o card sem custo não contribui com 0 "de propósito"
    assert d.custo_por_entrega == 2.0  # 4.0 / 2 entregas (a sem-custo entregou também)


def test_sem_cards_relatorio_vazio_nao_quebra() -> None:
    rel = consolidar("orch", [], [])
    assert rel.desempenho_por_executor == []
    assert rel.total_cards == 0
