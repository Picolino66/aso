"""Roteamento de falha — política pura (§13 do fluxo.md, ADR-0019).

`diagnosticar`/`decidir`/`proximo_effort`/`proximo_executor` são funções puras (sem
I/O): dado o mesmo `FailureRecord` e o mesmo catálogo, a decisão é sempre a mesma —
por isso testáveis isoladamente, sem worktree nem agente real.
"""

from __future__ import annotations

import pytest

from aso.control.failure import (
    ACAO_AUMENTAR_EFFORT,
    ACAO_BLOQUEAR,
    ACAO_ESCALAR_HUMANO,
    ACAO_MESMO_AGENTE,
    ACAO_TROCAR_EXECUTOR,
    DIAG_AGENTE_INDISPONIVEL,
    DIAG_DESCONHECIDO,
    DIAG_DIFF_VAZIO,
    DIAG_SEM_PERMISSAO,
    DIAG_TESTE_FALHOU,
    DIAG_TIMEOUT,
    FailureRecord,
    decidir,
    diagnosticar,
    proximo_effort,
    proximo_executor,
)
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile

# ---------------------------------------------------------------------- diagnosticar


def test_diagnostica_sem_permissao_a_partir_da_fala_do_agente() -> None:
    record = FailureRecord(
        mensagem=(
            "Executor CLI não produziu alterações no worktree (diff vazio). Última "
            "saída do agente: preciso de --dangerously-skip-permissions para editar"
        )
    )
    assert diagnosticar(record) == DIAG_SEM_PERMISSAO


def test_diagnostica_diff_vazio_sem_menção_de_permissao() -> None:
    record = FailureRecord(
        mensagem="Executor CLI não produziu alterações no worktree (diff vazio)."
    )
    assert diagnosticar(record) == DIAG_DIFF_VAZIO


def test_diagnostica_timeout() -> None:
    record = FailureRecord(
        mensagem="Executor CLI não terminou em 1800s e foi encerrado.",
        saida="subprocess.TimeoutExpired: comando expirou",
    )
    assert diagnosticar(record) == DIAG_TIMEOUT


def test_diagnostica_agente_indisponivel() -> None:
    record = FailureRecord(mensagem="Executor 'codex-default' indisponível: binário não encontrado")
    assert diagnosticar(record) == DIAG_AGENTE_INDISPONIVEL


def test_diagnostica_teste_falhou() -> None:
    saida = (
        "exit=1 tests/test_x.py::test_y FAILED\n"
        "AssertionError: 1 != 2\n"
        "Traceback (most recent call last):"
    )
    record = FailureRecord(mensagem="gate falhou", saida=saida)
    assert diagnosticar(record) == DIAG_TESTE_FALHOU


def test_diagnostica_desconhecido_sem_pista_nenhuma() -> None:
    record = FailureRecord(mensagem="algo inesperado aconteceu")
    assert diagnosticar(record) == DIAG_DESCONHECIDO


# --------------------------------------------------------------------------- decidir

_TABELA_ESPERADA: dict[str, list[str]] = {
    DIAG_SEM_PERMISSAO: [ACAO_BLOQUEAR],
    DIAG_TIMEOUT: [ACAO_AUMENTAR_EFFORT, ACAO_TROCAR_EXECUTOR, ACAO_ESCALAR_HUMANO],
    DIAG_TESTE_FALHOU: [
        ACAO_MESMO_AGENTE,
        ACAO_AUMENTAR_EFFORT,
        ACAO_TROCAR_EXECUTOR,
        ACAO_ESCALAR_HUMANO,
    ],
    DIAG_DIFF_VAZIO: [ACAO_MESMO_AGENTE, ACAO_TROCAR_EXECUTOR, ACAO_ESCALAR_HUMANO],
    DIAG_AGENTE_INDISPONIVEL: [ACAO_TROCAR_EXECUTOR, ACAO_ESCALAR_HUMANO],
    DIAG_DESCONHECIDO: [ACAO_MESMO_AGENTE, ACAO_ESCALAR_HUMANO],
}


def _catalogo_dois_clis() -> ExecutorCatalog:
    return ExecutorCatalog(
        [
            ExecutorProfile(name="a", kind="cli", command="a", effort="low"),
            ExecutorProfile(name="b", kind="cli", command="b", effort="low"),
        ]
    )


@pytest.mark.parametrize(
    ("diagnostico", "passos"),
    list(_TABELA_ESPERADA.items()),
)
def test_tabela_de_politica_inteira(diagnostico: str, passos: list[str]) -> None:
    catalogo = _catalogo_dois_clis()
    for tentativa, esperado in enumerate(passos, start=1):
        decisao = decidir(
            diagnostico,
            tentativa,
            executor_atual="a",
            effort_atual="low",
            catalogo=catalogo,
            max_escalonamentos=10,
        )
        assert decisao.acao == esperado, f"{diagnostico} tentativa {tentativa}"


def test_sem_permissao_nunca_re_tenta_mesmo_com_muitas_tentativas() -> None:
    for tentativa in (1, 2, 5, 10):
        decisao = decidir(DIAG_SEM_PERMISSAO, tentativa, max_escalonamentos=10)
        assert decisao.acao == ACAO_BLOQUEAR


def test_aumentar_effort_sem_catalogo_usa_a_escada_padrao() -> None:
    """Sem catálogo, `aumentar_effort` ainda resolve pela escada padrão
    (`low/medium/high`) — só `trocar_executor` depende do catálogo."""
    decisao = decidir(DIAG_TIMEOUT, 1, effort_atual="low", catalogo=None, max_escalonamentos=10)
    assert decisao.acao == ACAO_AUMENTAR_EFFORT
    assert decisao.effort == "medium"


def test_aumentar_effort_no_topo_sem_catalogo_cai_para_trocar_executor_e_escala() -> None:
    """Já no topo do effort e sem catálogo para trocar de executor: nenhum dos dois
    passos intermediários resolve, a política cai para `escalar_humano`."""
    decisao = decidir(DIAG_TIMEOUT, 1, effort_atual="high", catalogo=None, max_escalonamentos=10)
    assert decisao.acao == ACAO_ESCALAR_HUMANO


def test_trocar_executor_sem_alternativa_disponivel_escala() -> None:
    catalogo = ExecutorCatalog([ExecutorProfile(name="a", kind="cli", command="a")])
    decisao = decidir(
        DIAG_AGENTE_INDISPONIVEL, 1, executor_atual="a", catalogo=catalogo, max_escalonamentos=10
    )
    assert decisao.acao == ACAO_ESCALAR_HUMANO


def test_max_escalonamentos_esgotado_forca_escalar_humano() -> None:
    """Mesmo um diagnóstico com passo de retry disponível escala quando o limite
    duro (`ASO_MAX_ESCALONAMENTOS`) já foi ultrapassado — a rede de segurança do
    laço em `run_card` nunca reexecuta sem fim."""
    decisao = decidir(DIAG_TESTE_FALHOU, 4, catalogo=_catalogo_dois_clis(), max_escalonamentos=3)
    assert decisao.acao == ACAO_ESCALAR_HUMANO


def test_decisao_de_aumentar_effort_preenche_effort() -> None:
    decisao = decidir(
        DIAG_TIMEOUT,
        1,
        executor_atual="a",
        effort_atual="low",
        catalogo=_catalogo_dois_clis(),
        max_escalonamentos=10,
    )
    assert decisao.acao == ACAO_AUMENTAR_EFFORT
    assert decisao.effort == "medium"


def test_decisao_de_trocar_executor_preenche_executor() -> None:
    decisao = decidir(
        DIAG_AGENTE_INDISPONIVEL,
        1,
        executor_atual="a",
        catalogo=_catalogo_dois_clis(),
        max_escalonamentos=10,
    )
    assert decisao.acao == ACAO_TROCAR_EXECUTOR
    assert decisao.executor == "b"


# ------------------------------------------------------------------ proximo_effort


def test_proximo_effort_sobe_um_degrau() -> None:
    assert proximo_effort("low", ["low", "medium", "high"]) == "medium"
    assert proximo_effort("medium", ["low", "medium", "high"]) == "high"


def test_proximo_effort_none_no_topo() -> None:
    assert proximo_effort("high", ["low", "medium", "high"]) is None


def test_proximo_effort_respeita_supported_efforts_reduzido() -> None:
    """Perfil Codex gerenciado pode só aceitar um subconjunto — não pode sugerir um
    degrau que o perfil não suporta."""
    assert proximo_effort("low", ["low", "high"]) == "high"
    assert proximo_effort("high", ["low", "high"]) is None


# ------------------------------------------------------------------ proximo_executor


def test_proximo_executor_pula_indisponiveis_e_nunca_repete_o_atual() -> None:
    catalogo = ExecutorCatalog(
        [
            ExecutorProfile(name="a", kind="cli", command="a"),
            ExecutorProfile(name="b", kind="cli", command="b", available=False),
            ExecutorProfile(name="c", kind="cli", command="c"),
        ]
    )
    escolhido = proximo_executor("a", catalogo)
    assert escolhido == "c"


def test_proximo_executor_sem_alternativa_devolve_none() -> None:
    catalogo = ExecutorCatalog([ExecutorProfile(name="a", kind="cli", command="a")])
    assert proximo_executor("a", catalogo) is None


def test_proximo_executor_respeita_kind() -> None:
    catalogo = ExecutorCatalog(
        [
            ExecutorProfile(name="a", kind="cli", command="a"),
            ExecutorProfile(name="b", kind="llm", provider="deepseek", model="x"),
        ]
    )
    assert proximo_executor("a", catalogo) is None
