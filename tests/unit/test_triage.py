"""TriageService — ficha estruturada da demanda com fallback determinístico (§1/§2).

A regra que estes testes protegem: **triar nunca impede a criação de uma
orquestração**. Toda falha do agente (executor sumido do catálogo, JSON inválido,
exit != 0, timeout, tipo que não produz texto) tem que virar a ficha heurística +
motivo registrado, nunca exceção.
"""

from __future__ import annotations

import shlex

import pytest

from aso.control.models import AgentAssignment
from aso.control.triage import TIMEOUT_PADRAO, TriageService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.shared.types import RiskLevel


def _cli(saida: str, *, exit_code: int = 0) -> ExecutorCatalog:
    """Catálogo com um 'agente de triagem' que apenas cospe `saida` e sai com `exit_code`."""
    script = f'cat > /dev/null; printf %s "$1"; exit {exit_code}'
    comando = shlex.join(["bash", "-c", script, "_", saida])
    return ExecutorCatalog([ExecutorProfile(name="triador", kind="cli", command=comando)])


def _triar(service: TriageService, assignment: AgentAssignment | None, texto: str) -> object:
    return service.analisar(assignment, user_request=texto)


DEMANDA_RICA = (
    "Adicionar login com OAuth, guardando os tokens no banco de dados, "
    "com tela de consentimento para o usuário final."
)


# --------------------------------------------------------------- caminho feliz (agente)


def test_resposta_valida_do_agente_e_aceita_com_origem_do_executor() -> None:
    bruto = (
        '{"tipo": "funcionalidade", "objetivo": "Login social", '
        '"dominios": ["backend", "security"], "impactos": ["security"], '
        '"risco": "high", "complexidade": "complexa"}'
    )
    catalogo = _cli(bruto)
    ficha = _triar(TriageService(catalogo), AgentAssignment(executor="triador"), DEMANDA_RICA)
    assert ficha.objetivo == "Login social"
    assert ficha.dominios == ["backend", "security"]
    assert ficha.risco == RiskLevel.HIGH
    assert ficha.complexidade == "complexa"
    assert ficha.origem == "triador"  # origem = nome do executor
    assert ficha.fallback_reason == ""


def test_agente_que_devolve_json_em_cerca_de_codigo_funciona() -> None:
    bruto = '```json\n{"objetivo": "Exportar relatório"}\n```'
    ficha = _triar(TriageService(_cli(bruto)), AgentAssignment(executor="triador"), DEMANDA_RICA)
    assert ficha.objetivo == "Exportar relatório"


# ---------------------------------------------------------- saneamento do vocabulário


def test_dominio_e_impacto_desconhecidos_sao_descartados() -> None:
    bruto = (
        '{"objetivo": "x", "dominios": ["backend", "marketing"], '
        '"impactos": ["deploy", "espaco-sideral"]}'
    )
    ficha = _triar(TriageService(_cli(bruto)), AgentAssignment(executor="triador"), DEMANDA_RICA)
    assert ficha.dominios == ["backend"]
    assert ficha.impactos == ["deploy"]


def test_tipo_e_risco_invalidos_caem_no_padrao() -> None:
    bruto = '{"objetivo": "x", "tipo": "inventado", "risco": "catastrofico"}'
    ficha = _triar(TriageService(_cli(bruto)), AgentAssignment(executor="triador"), DEMANDA_RICA)
    assert ficha.tipo == "funcionalidade"
    assert ficha.risco == RiskLevel.LOW


# ------------------------------------------------------- as cinco falhas (nunca derruba)


def test_sem_agente_configurado_usa_a_heuristica() -> None:
    ficha = _triar(TriageService(_cli("{}")), None, DEMANDA_RICA)
    assert ficha.origem == "heuristica"
    assert ficha.fallback_reason == ""  # não é falha: é o padrão


def test_sem_catalogo_usa_a_heuristica() -> None:
    ficha = _triar(TriageService(None), AgentAssignment(executor="qualquer"), DEMANDA_RICA)
    assert ficha.origem == "heuristica"


def test_json_invalido_cai_na_heuristica_com_motivo() -> None:
    ficha = _triar(
        TriageService(_cli("desculpe, não entendi")),
        AgentAssignment(executor="triador"),
        DEMANDA_RICA,
    )
    assert ficha.origem == "heuristica"
    assert "ValueError" in ficha.fallback_reason or "LlmError" in ficha.fallback_reason


def test_agente_que_falha_cai_na_heuristica() -> None:
    catalogo = _cli("erro", exit_code=3)
    ficha = _triar(TriageService(catalogo), AgentAssignment(executor="triador"), DEMANDA_RICA)
    assert ficha.origem == "heuristica"
    assert "exit=3" in ficha.fallback_reason


def test_executor_fora_do_catalogo_cai_na_heuristica() -> None:
    ficha = _triar(TriageService(_cli("{}")), AgentAssignment(executor="apagado"), DEMANDA_RICA)
    assert ficha.origem == "heuristica"
    assert "não está no catálogo" in ficha.fallback_reason


def test_executor_mock_nao_produz_texto_cai_na_heuristica() -> None:
    ficha = _triar(TriageService(ExecutorCatalog()), AgentAssignment(executor="mock"), DEMANDA_RICA)
    assert ficha.origem == "heuristica"
    assert "não sabe produzir texto" in ficha.fallback_reason


def test_timeout_do_agente_cai_na_heuristica() -> None:
    catalogo = ExecutorCatalog(
        [ExecutorProfile(name="lento", kind="cli", command='bash -c "sleep 5"')]
    )
    ficha = _triar(
        TriageService(catalogo, timeout=0.2), AgentAssignment(executor="lento"), DEMANDA_RICA
    )
    assert ficha.origem == "heuristica"
    assert "Timeout" in ficha.fallback_reason


def test_resposta_sem_campos_utilizaveis_cai_na_heuristica() -> None:
    ficha = _triar(
        TriageService(_cli('{"dominios": [], "impactos": []}')),
        AgentAssignment(executor="triador"),
        DEMANDA_RICA,
    )
    assert ficha.origem == "heuristica"
    assert "utilizáveis" in ficha.fallback_reason


def test_timeout_padrao_maior_que_o_do_naming() -> None:
    assert TIMEOUT_PADRAO > 30.0


# --------------------------------------------------------------------- heurística


@pytest.mark.parametrize(
    ("texto", "dominios", "impactos"),
    [
        ("Corrigir bug no cálculo de frete", None, None),
        ("Ajustar schema da tabela de pedidos no banco", ["database"], ["database"]),
        ("Criar novo endpoint de contrato da API de pagamentos", ["contract"], ["contract"]),
        ("Revisar tela de login com token e senha de autenticação", ["security"], ["security"]),
        ("Publicar a versão nova em produção via deploy", None, ["deploy"]),
        ("Ajustar componente de UI da tela de checkout", ["frontend"], None),
        ("Aumentar a cobertura de teste do módulo de vendas", ["tests"], None),
        ("Documentar o README do módulo de vendas", ["docs"], None),
        ("Refatorar e reestruturar a arquitetura de pagamentos", None, ["architecture"]),
    ],
)
def test_heuristica_reconhece_cada_sinal(
    texto: str, dominios: list[str] | None, impactos: list[str] | None
) -> None:
    ficha = _triar(TriageService(None), None, texto)
    if dominios:
        for dominio in dominios:
            assert dominio in ficha.dominios
    if impactos:
        for impacto in impactos:
            assert impacto in ficha.impactos


def test_heuristica_de_correcao() -> None:
    ficha = _triar(TriageService(None), None, "Corrigir bug crítico no cálculo do frete")
    assert ficha.tipo == "correcao"


def test_heuristica_de_documentacao() -> None:
    ficha = _triar(TriageService(None), None, "Documentar o módulo de vendas no readme")
    assert ficha.tipo == "documentacao"


def test_heuristica_eleva_risco_em_seguranca() -> None:
    ficha = _triar(TriageService(None), None, "Ajustar login com token e senha de autenticacao")
    assert ficha.risco == RiskLevel.HIGH


def test_heuristica_sem_nenhum_sinal_preserva_o_comportamento_de_hoje() -> None:
    ficha = _triar(TriageService(None), None, "Ajustar o relatório mensal de vendas totais")
    assert ficha.dominios == ["backend"]
    assert ficha.risco == RiskLevel.LOW


@pytest.mark.parametrize("texto", ["", "melhorar", "   "])
def test_texto_vazio_ou_trivial_gera_perguntas_abertas(texto: str) -> None:
    ficha = _triar(TriageService(None), None, texto)
    assert ficha.perguntas_abertas


def test_texto_rico_nao_gera_perguntas_abertas() -> None:
    ficha = _triar(TriageService(None), None, DEMANDA_RICA)
    assert ficha.perguntas_abertas == []


# ---------------------------------------------------------------------- to_decision_input


def test_to_decision_input_mapeia_risco_e_dominios() -> None:
    ficha = _triar(TriageService(None), None, "Ajustar schema do banco e endpoint da API")
    din = ficha.to_decision_input("demanda")
    assert din.risk_level == ficha.risco
    assert set(din.domains) == set(ficha.dominios)


def test_to_decision_input_parallelizable_falso_com_impacto_contract() -> None:
    ficha = _triar(TriageService(None), None, "Ajustar endpoint da API e a tela de checkout")
    assert "contract" in ficha.impactos
    din = ficha.to_decision_input("demanda")
    assert din.parallelizable is False


def test_to_decision_input_sem_sinal_reproduz_o_padrao_de_hoje() -> None:
    ficha = _triar(TriageService(None), None, "Ajustar o relatório mensal de vendas totais")
    din = ficha.to_decision_input("demanda qualquer")
    assert din.domains == ["backend"]
    assert din.risk_level == RiskLevel.LOW
    assert din.parallelizable is False
    assert din.needs_independent_review is False
    assert din.impacts == []
