"""MEL-41 — uso e custo de todos os executores (ADR-0070)."""

from __future__ import annotations

import json

import pytest

from aso.execution.agent_stream import extrair_uso
from aso.execution.llm_client import FakeLlmClient, completar, uso_anthropic, uso_openai
from aso.execution.precos import PrecoDoModelo, precificar, tabela_do_ambiente
from aso.shared.agent_usage import (
    ORIGEM_AGENTE,
    ORIGEM_INDISPONIVEL,
    ORIGEM_TABELA,
    ORIGEM_TOKENS,
    UsoDoAgente,
    acumular_uso,
)

TABELA = {"gpt-x": PrecoDoModelo(entrada=2.0, saida=8.0, cache_leitura=0.5)}


def test_precifica_tokens_pela_tabela() -> None:
    uso = UsoDoAgente(
        tokens_entrada=1_000_000,
        tokens_saida=500_000,
        tokens_cache_leitura=200_000,
        modelo="gpt-x",
        origem=ORIGEM_TOKENS,
    )
    precificado = precificar(uso, tabela=TABELA)
    assert precificado.origem == ORIGEM_TABELA
    assert precificado.custo_usd == pytest.approx(2.0 + 4.0 + 0.1)
    assert precificar(precificado, tabela=TABELA) == precificado  # idempotente


def test_sem_preco_tokens_ficam_e_custo_indisponivel() -> None:
    uso = UsoDoAgente(tokens_entrada=10, tokens_saida=5, origem=ORIGEM_TOKENS)
    resultado = precificar(uso, modelo_padrao="sem-preco", tabela=TABELA)
    assert resultado.origem == ORIGEM_TOKENS and resultado.custo_usd == 0.0
    assert resultado.modelo == "sem-preco" and resultado.tokens_entrada == 10


def test_custo_informado_pelo_agente_nao_e_recalculado() -> None:
    uso = UsoDoAgente(tokens_entrada=10, custo_usd=0.3, modelo="gpt-x", origem=ORIGEM_AGENTE)
    assert precificar(uso, tabela=TABELA) == uso


def test_tabela_do_ambiente_ignora_json_invalido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASO_PRECOS_MODELOS", "{não é json")
    assert tabela_do_ambiente() == {}
    monkeypatch.setenv(
        "ASO_PRECOS_MODELOS", json.dumps({"m": {"entrada": 1, "saida": "2"}, "ruim": 3})
    )
    assert tabela_do_ambiente() == {"m": PrecoDoModelo(entrada=1.0, saida=2.0)}


def test_uso_openai_separa_cache_da_entrada() -> None:
    payload = {
        "model": "gpt-x",
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 30},
        },
    }
    uso = uso_openai(payload, "fallback")
    assert (uso.tokens_entrada, uso.tokens_saida, uso.tokens_cache_leitura) == (70, 20, 30)
    assert uso.modelo == "gpt-x" and uso.origem == ORIGEM_TOKENS
    assert uso_openai({}, "m").origem == ORIGEM_INDISPONIVEL


def test_uso_anthropic_le_cache_de_leitura_e_escrita() -> None:
    payload = {
        "usage": {
            "input_tokens": 50,
            "output_tokens": 9,
            "cache_read_input_tokens": 7,
            "cache_creation_input_tokens": 3,
        }
    }
    uso = uso_anthropic(payload, "claude-x")
    assert (uso.tokens_entrada, uso.tokens_saida) == (50, 9)
    assert (uso.tokens_cache_leitura, uso.tokens_cache_escrita) == (7, 3)
    assert uso.modelo == "claude-x"


def test_codex_turn_completed_vira_tokens_sem_custo() -> None:
    linha = json.dumps(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 1200,
                "cached_input_tokens": 200,
                "output_tokens": 300,
                "reasoning_output_tokens": 100,
            },
        }
    )
    uso = extrair_uso(linha)
    assert uso is not None and uso.origem == ORIGEM_TOKENS
    assert (uso.tokens_entrada, uso.tokens_cache_leitura, uso.tokens_saida) == (1000, 200, 300)
    assert extrair_uso(json.dumps({"type": "turn.completed"})) is None


def test_execucao_com_custo_calculado_nao_conta_como_sem_custo() -> None:
    total = acumular_uso({}, UsoDoAgente(tokens_entrada=5, custo_usd=0.01, origem=ORIGEM_TABELA))
    total = acumular_uso(total, UsoDoAgente(tokens_entrada=5, origem=ORIGEM_TOKENS))
    assert total["execucoes"] == 2 and total["execucoes_sem_custo"] == 1
    assert total["tokens_entrada"] == 10


def test_fake_llm_e_cliente_sem_completar_devolvem_resposta() -> None:
    uso = UsoDoAgente(tokens_entrada=1, origem=ORIGEM_TOKENS)
    assert completar(FakeLlmClient(default="oi", uso=uso), system="s", user="u").uso == uso

    class _Legado:
        id = "legado"

        def complete(self, *, system: str, user: str) -> str:
            return "texto"

    resposta = completar(_Legado(), system="s", user="u")
    assert resposta.texto == "texto" and resposta.uso.origem == ORIGEM_INDISPONIVEL
