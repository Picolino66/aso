"""ReviewService — revisão independente a partir do diff (§14, ADR-0017).

A regra que estes testes protegem: **o fallback deste serviço nunca é `aprovado`**.
Diferente de naming/triage (que caem em determinismo/heurística e continuam
funcionando sem agente), não existe revisão de código determinística — qualquer
falha do revisor tem que escalar para `necessita_humano`, nunca aprovar sozinha.
"""

from __future__ import annotations

import shlex

from aso.control.models import AgentAssignment
from aso.control.review import (
    DIFF_MAX,
    TIMEOUT_PADRAO,
    VEREDITO_APROVADO,
    VEREDITO_NECESSITA_HUMANO,
    ReviewService,
)
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile

DIFF_EXEMPLO = "diff --git a/x.py b/x.py\n+def x():\n+    return 1\n"


def _cli(saida: str, *, exit_code: int = 0) -> ExecutorCatalog:
    """Catálogo com um 'agente revisor' que apenas cospe `saida` e sai com `exit_code`."""
    script = f'cat > /dev/null; printf %s "$1"; exit {exit_code}'
    comando = shlex.join(["bash", "-c", script, "_", saida])
    return ExecutorCatalog([ExecutorProfile(name="revisor", kind="cli", command=comando)])


def _revisar(service: ReviewService, assignment: AgentAssignment | None) -> object:
    return service.revisar(
        assignment,
        diff=DIFF_EXEMPLO,
        card_title="Implementar cálculo de frete",
        card_description="Cálculo baseado em peso e distância.",
        acceptance_criteria=["Frete nunca é negativo"],
        riscos=["cálculo pode divergir do legado"],
    )


# --------------------------------------------------------------- caminho feliz (agente)


def test_veredito_valido_aprovado_e_aceito_com_origem_do_executor() -> None:
    bruto = (
        '{"veredito": "aprovado", "resumo": "Diff pequeno e correto.", '
        '"pontos_verificados": ["correção", "testes"]}'
    )
    verdito = _revisar(ReviewService(_cli(bruto)), AgentAssignment(executor="revisor"))
    assert verdito.veredito == VEREDITO_APROVADO
    assert verdito.resumo == "Diff pequeno e correto."
    assert verdito.origem == "agente"
    assert verdito.revisor == "revisor"
    assert verdito.fallback_reason == ""


def test_veredito_aprovado_com_sugestoes_e_aceito() -> None:
    bruto = '{"veredito": "aprovado_com_sugestoes", "resumo": "ok"}'
    verdito = _revisar(ReviewService(_cli(bruto)), AgentAssignment(executor="revisor"))
    assert verdito.veredito == "aprovado_com_sugestoes"


def test_veredito_alteracoes_obrigatorias_com_acoes() -> None:
    bruto = (
        '{"veredito": "alteracoes_obrigatorias", "resumo": "faltou teste", '
        '"acoes": [{"descricao": "Adicionar teste para frete negativo", '
        '"categoria": "teste", "severidade": "obrigatoria"}]}'
    )
    verdito = _revisar(ReviewService(_cli(bruto)), AgentAssignment(executor="revisor"))
    assert verdito.veredito == "alteracoes_obrigatorias"
    assert len(verdito.acoes) == 1
    assert verdito.acoes[0].descricao == "Adicionar teste para frete negativo"
    assert verdito.acoes[0].categoria == "teste"
    assert verdito.acoes[0].severidade == "obrigatoria"


def test_veredito_reprovado_e_aceito() -> None:
    bruto = '{"veredito": "reprovado", "resumo": "quebra contrato existente"}'
    verdito = _revisar(ReviewService(_cli(bruto)), AgentAssignment(executor="revisor"))
    assert verdito.veredito == "reprovado"


def test_veredito_necessita_humano_do_proprio_agente_e_aceito() -> None:
    bruto = '{"veredito": "necessita_humano", "resumo": "diff toca área sensível"}'
    verdito = _revisar(ReviewService(_cli(bruto)), AgentAssignment(executor="revisor"))
    assert verdito.veredito == VEREDITO_NECESSITA_HUMANO
    assert verdito.origem == "agente"  # o agente rodou; só o veredito é conservador


def test_agente_que_devolve_json_em_cerca_de_codigo_funciona() -> None:
    bruto = '```json\n{"veredito": "aprovado", "resumo": "ok"}\n```'
    verdito = _revisar(ReviewService(_cli(bruto)), AgentAssignment(executor="revisor"))
    assert verdito.veredito == VEREDITO_APROVADO


# ---------------------------------------------------------- saneamento do vocabulário


def test_veredito_categoria_e_severidade_fora_do_vocabulario_caem_no_padrao() -> None:
    bruto = (
        '{"veredito": "aprovadissimo", "resumo": "x", '
        '"acoes": [{"descricao": "corrigir algo", "categoria": "esoterismo", '
        '"severidade": "talvez"}]}'
    )
    verdito = _revisar(ReviewService(_cli(bruto)), AgentAssignment(executor="revisor"))
    # Veredito desconhecido cai no padrão mais conservador — nunca em "aprovado".
    assert verdito.veredito == VEREDITO_NECESSITA_HUMANO
    assert verdito.acoes[0].categoria == "correcao"
    assert verdito.acoes[0].severidade == "obrigatoria"


def test_acao_sem_descricao_e_descartada() -> None:
    bruto = '{"veredito": "aprovado", "acoes": [{"categoria": "teste"}]}'
    verdito = _revisar(ReviewService(_cli(bruto)), AgentAssignment(executor="revisor"))
    assert verdito.acoes == []


# --------------------------------------------------------- os seis caminhos (nunca aprova)


def test_sem_agente_configurado_e_necessita_humano() -> None:
    verdito = _revisar(ReviewService(_cli("{}")), None)
    assert verdito.veredito == VEREDITO_NECESSITA_HUMANO
    assert verdito.origem == "indisponivel"
    assert verdito.veredito != VEREDITO_APROVADO


def test_sem_catalogo_e_necessita_humano() -> None:
    verdito = _revisar(ReviewService(None), AgentAssignment(executor="qualquer"))
    assert verdito.veredito == VEREDITO_NECESSITA_HUMANO
    assert verdito.origem == "indisponivel"


def test_json_invalido_e_necessita_humano_com_motivo() -> None:
    verdito = _revisar(
        ReviewService(_cli("desculpe, não entendi")), AgentAssignment(executor="revisor")
    )
    assert verdito.veredito == VEREDITO_NECESSITA_HUMANO
    assert verdito.origem == "indisponivel"
    assert "ValueError" in verdito.fallback_reason or "LlmError" in verdito.fallback_reason


def test_agente_que_falha_e_necessita_humano() -> None:
    verdito = _revisar(
        ReviewService(_cli("erro", exit_code=3)), AgentAssignment(executor="revisor")
    )
    assert verdito.veredito == VEREDITO_NECESSITA_HUMANO
    assert verdito.origem == "indisponivel"
    assert "exit=3" in verdito.fallback_reason


def test_executor_fora_do_catalogo_e_necessita_humano() -> None:
    verdito = _revisar(ReviewService(_cli("{}")), AgentAssignment(executor="apagado"))
    assert verdito.veredito == VEREDITO_NECESSITA_HUMANO
    assert verdito.origem == "indisponivel"
    assert "não está no catálogo" in verdito.fallback_reason


def test_executor_mock_nao_produz_texto_e_necessita_humano() -> None:
    verdito = _revisar(ReviewService(ExecutorCatalog()), AgentAssignment(executor="mock"))
    assert verdito.veredito == VEREDITO_NECESSITA_HUMANO
    assert verdito.origem == "indisponivel"
    assert "não sabe produzir texto" in verdito.fallback_reason


def test_timeout_do_agente_e_necessita_humano() -> None:
    catalogo = ExecutorCatalog(
        [ExecutorProfile(name="lento", kind="cli", command='bash -c "sleep 5"')]
    )
    verdito = _revisar(ReviewService(catalogo, timeout=0.2), AgentAssignment(executor="lento"))
    assert verdito.veredito == VEREDITO_NECESSITA_HUMANO
    assert verdito.origem == "indisponivel"
    assert "Timeout" in verdito.fallback_reason


def test_resposta_sem_campos_utilizaveis_e_necessita_humano() -> None:
    verdito = _revisar(ReviewService(_cli("{}")), AgentAssignment(executor="revisor"))
    assert verdito.veredito == VEREDITO_NECESSITA_HUMANO
    assert verdito.origem == "indisponivel"
    assert "utilizável" in verdito.fallback_reason


def test_timeout_padrao_e_bem_maior_que_o_da_triagem() -> None:
    assert TIMEOUT_PADRAO > 45.0


# --------------------------------------------------------------------- truncamento do diff


def test_diff_acima_do_limite_e_truncado_e_avisa() -> None:
    diff_gigante = "+linha\n" * (DIFF_MAX // 6 + 1000)
    assert len(diff_gigante) > DIFF_MAX
    bruto = '{"veredito": "aprovado", "resumo": "ok"}'
    catalogo = _cli(bruto)
    verdito = ReviewService(catalogo).revisar(
        AgentAssignment(executor="revisor"),
        diff=diff_gigante,
        card_title="Card gigante",
    )
    assert any("truncado" in p for p in verdito.pontos_verificados)


def test_diff_pequeno_nao_e_truncado() -> None:
    bruto = '{"veredito": "aprovado", "resumo": "ok", "pontos_verificados": ["correção"]}'
    verdito = _revisar(ReviewService(_cli(bruto)), AgentAssignment(executor="revisor"))
    assert not any("truncado" in p for p in verdito.pontos_verificados)
