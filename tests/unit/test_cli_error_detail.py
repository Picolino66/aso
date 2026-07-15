"""Erros CLI não devem despejar prompt e JSON bruto na interface."""

from aso.execution.cli_provider import _failure_detail


def test_extrai_e_deduplica_erro_codex() -> None:
    raw = """prompt enorme e sensível
ERROR: {"error":{"message":"modelo não suportado"}}
ERROR: {"error":{"message":"modelo não suportado"}}
"""
    assert _failure_detail(raw) == "modelo não suportado"


def test_fallback_limita_saida() -> None:
    assert len(_failure_detail("x" * 900)) == 600
