"""Erros CLI não devem despejar prompt e JSON bruto na interface."""

from aso.execution.cli_provider import _empty_diff_detail, _failure_detail


def test_extrai_e_deduplica_erro_codex() -> None:
    raw = """prompt enorme e sensível
ERROR: {"error":{"message":"modelo não suportado"}}
ERROR: {"error":{"message":"modelo não suportado"}}
"""
    assert _failure_detail(raw) == "modelo não suportado"


def test_fallback_limita_saida() -> None:
    assert len(_failure_detail("x" * 900)) == 600


def test_diff_vazio_preserva_a_ultima_fala_do_agente() -> None:
    """Sem a fala do agente, 'diff vazio' não distingue falta de permissão de preguiça."""
    detalhe = _empty_diff_detail("Vou aguardar sua permissão para criar o arquivo.", "")
    assert "diff vazio" in detalhe
    assert "aguardar sua permissão" in detalhe


def test_diff_vazio_usa_stderr_quando_nao_ha_stdout() -> None:
    assert "permission denied" in _empty_diff_detail("", "permission denied")


def test_diff_vazio_sem_saida_orienta_a_conferir_o_comando() -> None:
    assert "confira o comando do executor" in _empty_diff_detail("", "")


def test_diff_vazio_limita_o_trecho_da_saida() -> None:
    assert len(_empty_diff_detail("y" * 900, "")) < 500
