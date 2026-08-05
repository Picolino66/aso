"""Consumo real do agente (§1.1/§26A.11 do plano7.md) — ADR-0026.

O envelope `_ENVELOPE_RESULT` usa o schema **documentado** pela Anthropic para o
`type == "result"` do Claude Code (`usage.*`, `total_cost_usd`) — diferente de
`test_agent_stream.py`, que tem uma captura real de execução, este runtime ainda não
exercitou uma execução real com `usage` populado (roteiro manual do plano7 §7, passo
1, é quem fecha essa lacuna). `extrair_uso` é deliberadamente defensivo: qualquer
chave ausente ou schema diferente do esperado cai em `None`, nunca em exceção.
"""

from __future__ import annotations

from aso.execution.agent_stream import extrair_uso
from aso.shared.agent_usage import ORIGEM_AGENTE, ORIGEM_INDISPONIVEL, acumular_uso

_ENVELOPE_RESULT = (
    '{"type":"result","subtype":"success","is_error":false,"result":"oi",'
    '"total_cost_usd":0.0123,"model":"claude-sonnet-5",'
    '"usage":{"input_tokens":100,"output_tokens":50,'
    '"cache_read_input_tokens":10,"cache_creation_input_tokens":5}}'
)


def test_extrair_uso_do_envelope_result() -> None:
    uso = extrair_uso(_ENVELOPE_RESULT)
    assert uso is not None
    assert uso.tokens_entrada == 100
    assert uso.tokens_saida == 50
    assert uso.tokens_cache_leitura == 10
    assert uso.tokens_cache_escrita == 5
    assert uso.custo_usd == 0.0123
    assert uso.modelo == "claude-sonnet-5"
    assert uso.origem == ORIGEM_AGENTE


def test_extrair_uso_sem_usage_devolve_none() -> None:
    assert extrair_uso('{"type":"result","subtype":"success","result":"oi"}') is None


def test_extrair_uso_tipo_diferente_de_result_devolve_none() -> None:
    assert extrair_uso('{"type":"assistant","message":{"content":[]}}') is None


def test_extrair_uso_schema_desconhecido_nao_lanca() -> None:
    assert extrair_uso('{"type":"result","usage":"não é um dict"}') is None
    assert extrair_uso("não é json") is None
    assert extrair_uso('{"type":"item.completed","item":{"usage":{}}}') is None


def test_origem_indisponivel_distinta_de_custo_zero() -> None:
    """Um `UsoDoAgente()` default nunca deve ser lido como "execução gratuita"."""
    default = extrair_uso('{"type":"result"}')
    assert default is None  # o chamador (cli_provider) usa o default da dataclass
    from aso.shared.agent_usage import UsoDoAgente

    indisponivel = UsoDoAgente()
    assert indisponivel.origem == ORIGEM_INDISPONIVEL
    assert indisponivel.custo_usd == 0.0  # zero por ausência de dado, não por ter custado zero


def test_acumular_uso_soma_reexecucoes() -> None:
    from aso.shared.agent_usage import UsoDoAgente

    primeiro = acumular_uso(
        {}, UsoDoAgente(tokens_entrada=10, custo_usd=0.01, origem=ORIGEM_AGENTE)
    )
    segundo = acumular_uso(
        primeiro, UsoDoAgente(tokens_entrada=20, custo_usd=0.02, origem=ORIGEM_AGENTE)
    )
    assert segundo["tokens_entrada"] == 30
    assert round(segundo["custo_usd"], 4) == 0.03
    assert segundo["execucoes"] == 2
    assert segundo["execucoes_sem_custo"] == 0


def test_acumular_uso_conta_execucoes_sem_custo_sem_somar_zero() -> None:
    from aso.shared.agent_usage import UsoDoAgente

    com_custo = acumular_uso({}, UsoDoAgente(custo_usd=1.0, origem=ORIGEM_AGENTE))
    sem_custo = acumular_uso(com_custo, UsoDoAgente())  # provider mock: origem indisponível
    assert sem_custo["execucoes"] == 2
    assert sem_custo["execucoes_sem_custo"] == 1
    assert sem_custo["custo_usd"] == 1.0  # a execução sem custo não subtrai nem soma 0 ao total
