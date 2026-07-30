"""NamingService — agente nomeador opcional com fallback determinístico (ADR-0014).

A regra que estes testes protegem: **nomear nunca derruba um card**. Toda falha do
agente (executor sumido do catálogo, JSON inválido, exit != 0, timeout, tipo que não
produz texto) tem que virar nome determinístico + motivo registrado, nunca exceção.
"""

from __future__ import annotations

import shlex

import pytest

from aso.control.models import AgentAssignment
from aso.control.naming import ASSUNTO_MAX, NamingService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.shared.types import CardType


def _cli(saida: str, *, exit_code: int = 0) -> ExecutorCatalog:
    """Catálogo com um 'agente CLI' que apenas cospe `saida` e sai com `exit_code`.

    A saída vai como argumento (`$1`) em vez de embutida no script: o JSON tem aspas e
    chaves que seriam destroçadas pelo `shlex.split` que o catálogo aplica ao comando.
    """
    script = f'cat > /dev/null; printf %s "$1"; exit {exit_code}'
    comando = shlex.join(["bash", "-c", script, "_", saida])
    return ExecutorCatalog([ExecutorProfile(name="nomeador", kind="cli", command=comando)])


def _sugerir(service: NamingService, assignment: AgentAssignment | None) -> object:
    return service.suggest(
        assignment,
        card_type=CardType.FEATURE,
        title="Calculadora básica",
        description="Somar, subtrair, multiplicar e dividir",
        acceptance_criteria=["Quatro operações funcionam", "Testes verdes"],
        phase="F5",
    )


def test_sem_agente_configurado_usa_o_deterministico() -> None:
    nomes = _sugerir(NamingService(_cli("{}")), None)
    assert nomes.branch_stem == "feat/calculadora-basica"
    assert nomes.commit_subject == "feat: Calculadora básica"
    assert nomes.source == "deterministico"
    assert nomes.fallback_reason == ""  # não é falha: é o padrão


def test_sem_catalogo_usa_o_deterministico() -> None:
    nomes = _sugerir(NamingService(None), AgentAssignment(executor="qualquer"))
    assert nomes.source == "deterministico"


def test_resposta_valida_do_agente_e_aceita_e_saneada() -> None:
    catalogo = _cli('{"branch": "Calc/Cálculo Rápido!!", "commit": "feat: soma e subtração"}')
    nomes = _sugerir(NamingService(catalogo), AgentAssignment(executor="nomeador"))
    # O prefixo é imposto por nós; do agente só aproveitamos o miolo do slug.
    assert nomes.branch_stem == "feat/calculo-rapido"
    assert nomes.commit_subject == "feat: soma e subtração"
    assert nomes.source == "agente"


def test_agente_que_devolve_json_em_cerca_de_codigo_funciona() -> None:
    catalogo = _cli('```json\n{"branch": "historico", "commit": "feat: histórico"}\n```')
    nomes = _sugerir(NamingService(catalogo), AgentAssignment(executor="nomeador"))
    assert nomes.branch_stem == "feat/historico"


def test_agente_sem_prefixo_no_commit_recebe_o_nosso() -> None:
    catalogo = _cli('{"branch": "historico", "commit": "adiciona o histórico"}')
    nomes = _sugerir(NamingService(catalogo), AgentAssignment(executor="nomeador"))
    assert nomes.commit_subject == "feat: adiciona o histórico"


def test_assunto_gigante_do_agente_e_truncado() -> None:
    catalogo = _cli('{"branch": "x", "commit": "feat: ' + "a" * 200 + '"}')
    nomes = _sugerir(NamingService(catalogo), AgentAssignment(executor="nomeador"))
    assert len(nomes.commit_subject) <= ASSUNTO_MAX


def test_json_invalido_cai_no_deterministico_com_motivo() -> None:
    nomes = _sugerir(
        NamingService(_cli("desculpe, não entendi")), AgentAssignment(executor="nomeador")
    )
    assert nomes.branch_stem == "feat/calculadora-basica"
    assert nomes.source == "deterministico"
    assert nomes.fallback_reason  # o motivo fica registrado para auditoria


def test_agente_que_falha_cai_no_deterministico() -> None:
    catalogo = _cli("erro", exit_code=3)
    nomes = _sugerir(NamingService(catalogo), AgentAssignment(executor="nomeador"))
    assert nomes.source == "deterministico"
    assert "exit=3" in nomes.fallback_reason


def test_timeout_do_agente_cai_no_deterministico() -> None:
    catalogo = ExecutorCatalog(
        [ExecutorProfile(name="lento", kind="cli", command='bash -c "sleep 5"')]
    )
    nomes = _sugerir(NamingService(catalogo, timeout=0.2), AgentAssignment(executor="lento"))
    assert nomes.source == "deterministico"
    assert "Timeout" in nomes.fallback_reason


def test_executor_fora_do_catalogo_cai_no_deterministico() -> None:
    nomes = _sugerir(NamingService(_cli("{}")), AgentAssignment(executor="apagado"))
    assert nomes.source == "deterministico"
    assert "não está no catálogo" in nomes.fallback_reason


def test_executor_mock_nao_produz_texto_e_cai_no_deterministico() -> None:
    nomes = _sugerir(NamingService(ExecutorCatalog()), AgentAssignment(executor="mock"))
    assert nomes.source == "deterministico"
    assert "não sabe produzir texto" in nomes.fallback_reason


def test_resposta_vazia_do_agente_cai_no_deterministico() -> None:
    catalogo = _cli('{"branch": "", "commit": ""}')
    nomes = _sugerir(NamingService(catalogo), AgentAssignment(executor="nomeador"))
    assert nomes.source == "deterministico"
    assert "utilizáveis" in nomes.fallback_reason


@pytest.mark.parametrize("titulo", ["", "🚀", "   "])
def test_titulo_impraticavel_ainda_gera_branch_valida(titulo: str) -> None:
    nomes = NamingService(None).suggest(None, card_type=CardType.BUG, title=titulo)
    assert nomes.branch_stem == "fix/card"
    assert nomes.commit_subject == "fix: atualiza o card"
