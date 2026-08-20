"""Histórico de tentativas por card (§36.4 do wiframe) — ADR-0031."""

from __future__ import annotations

from aso.control.attempts import (
    RESULTADO_FALHOU,
    RESULTADO_SUCESSO,
    TentativaRegistro,
    registrar_tentativa,
)


def test_registrar_tentativa_adiciona_com_todos_os_campos() -> None:
    registro = TentativaRegistro(
        numero=1, executor="claude-code", effort="medium", resultado=RESULTADO_FALHOU
    )
    tentativas = registrar_tentativa([], registro)
    assert len(tentativas) == 1
    assert tentativas[0]["numero"] == 1
    assert tentativas[0]["executor"] == "claude-code"
    assert tentativas[0]["effort"] == "medium"
    assert tentativas[0]["resultado"] == RESULTADO_FALHOU
    assert tentativas[0]["at"]


def test_registrar_tentativa_aceita_sucesso() -> None:
    registro = TentativaRegistro(numero=3, resultado=RESULTADO_SUCESSO)
    tentativas = registrar_tentativa([], registro)
    assert tentativas[0]["resultado"] == RESULTADO_SUCESSO


def test_registrar_tentativa_default_e_falhou() -> None:
    assert TentativaRegistro(numero=1).resultado == RESULTADO_FALHOU


def test_ring_descarta_o_mais_antigo_alem_do_limite() -> None:
    tentativas: list[dict[str, object]] = []
    for i in range(1, 13):
        tentativas = registrar_tentativa(tentativas, TentativaRegistro(numero=i), limite=10)
    assert len(tentativas) == 10
    assert tentativas[0]["numero"] == 3  # os 2 primeiros (1, 2) foram descartados
    assert tentativas[-1]["numero"] == 12


def test_ring_abaixo_do_limite_mantem_tudo() -> None:
    tentativas: list[dict[str, object]] = []
    for i in range(1, 4):
        tentativas = registrar_tentativa(tentativas, TentativaRegistro(numero=i), limite=10)
    assert len(tentativas) == 3
