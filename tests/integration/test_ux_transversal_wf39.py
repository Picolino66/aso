"""Requisitos de UX obrigatórios (Tela 39, wf §39, ADR-0054) aplicados
transversalmente. Cada teste trava uma das lacunas reais fechadas pelo
FID-27 — regressão futura em qualquer uma delas quebra este arquivo, não
uma inspeção manual tela a tela.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_aprovacoes_pede_confirmacao_e_resume_criterios_antes_de_decidir() -> None:
    """Requisitos #4 (mostra critérios) e #8 (confirmação em ação irreversível)."""
    pagina = _client().get("/ui/aprovacoes").text
    assert "confirm(" in pagina
    assert "resumoCriterios" in pagina
    assert "irreversível" in pagina


def test_aprovacoes_distingue_origem_automatica_de_manual_com_pill() -> None:
    """Requisito #10 (decisão automática distinguida da humana)."""
    pagina = _client().get("/ui/aprovacoes").text
    assert "automática (" in pagina


def test_execucoes_mostra_agente_modelo_e_effort() -> None:
    """Requisito #5 (toda execução mostra agente, modelo e effort)."""
    pagina = _client().get("/ui/execucoes").text
    assert "<th>Modelo</th>" in pagina
    assert "c.executor" in pagina


def test_auditoria_navega_da_evidencia_de_volta_ate_card_e_demanda() -> None:
    """Requisito #7 (navegar da demanda até qualquer evidência, nos dois sentidos)."""
    pagina = _client().get("/ui/auditoria").text
    assert "/ui/card-detalhe?id=" in pagina
    assert "/ui/demanda-detalhe?id=" in pagina


def test_card_detalhe_e_demanda_detalhe_destacam_risco_critico() -> None:
    """Requisito #9 (a interface deve destacar riscos críticos)."""
    for rota in ("/ui/card-detalhe", "/ui/demanda-detalhe"):
        pagina = _client().get(rota).text
        assert "pillRisco" in pagina, rota
        assert "TOM_RISCO" in pagina, rota


def test_card_detalhe_marca_retorno_de_fluxo_na_timeline() -> None:
    """Requisito #6 (todo retorno de fluxo deve ser visualmente identificado)."""
    pagina = _client().get("/ui/card-detalhe").text
    assert "ehRetornoDeFluxo" in pagina
    assert "retorno" in pagina.lower()


def test_card_detalhe_reexibe_proxima_acao_na_aba_falhas() -> None:
    """Requisito #2 (toda falha deve indicar a próxima ação) — antes só na aba
    Histórico, agora reexibido também na aba Falhas."""
    pagina = _client().get("/ui/card-detalhe").text
    assert "Próxima ação recomendada" in pagina


def test_demanda_detalhe_historico_expoe_payload_dos_eventos_de_dominio() -> None:
    """Histórico da demanda (eventos de domínio) parava de renderizar tudo além de
    tipo/data — o payload livre de cada evento agora é exibido por completo."""
    pagina = _client().get("/ui/demanda-detalhe").text
    assert "e.payload" in pagina
    assert "append-only, nunca sobrescrito" in pagina
