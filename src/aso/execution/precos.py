"""Tabela de preços por modelo para custo de execuções que só informam tokens (ADR-0070).

Claude Code informa `total_cost_usd`; APIs compatíveis com OpenAI, Anthropic e o Codex só
informam tokens. Sem custo, o freio de orçamento (ADR-0026) e o limite por agente nunca
disparavam. `ASO_PRECOS_MODELOS` (JSON) dá o preço em USD **por milhão de tokens**:

    {"gpt-5.1": {"entrada": 1.25, "saida": 10, "cache_leitura": 0.125},
     "claude-sonnet-4-5": {"entrada": 3, "saida": 15, "cache_leitura": 0.3,
                           "cache_escrita": 3.75}}

Sem preço para o modelo, os tokens ficam registrados e o custo continua **indisponível** —
nunca um zero inventado.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace

from aso.shared.agent_usage import ORIGEM_TABELA, ORIGEM_TOKENS, UsoDoAgente

_POR_MILHAO = 1_000_000


@dataclass(frozen=True)
class PrecoDoModelo:
    entrada: float = 0.0
    saida: float = 0.0
    cache_leitura: float = 0.0
    cache_escrita: float = 0.0


def tabela_do_ambiente() -> dict[str, PrecoDoModelo]:
    """Lê `ASO_PRECOS_MODELOS`; JSON inválido ou entradas malformadas são ignorados."""
    bruto = os.environ.get("ASO_PRECOS_MODELOS", "").strip()
    if not bruto:
        return {}
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError:
        return {}
    if not isinstance(dados, dict):
        return {}
    tabela: dict[str, PrecoDoModelo] = {}
    for modelo, precos in dados.items():
        if not isinstance(precos, dict):
            continue
        try:
            tabela[str(modelo)] = PrecoDoModelo(
                **{k: float(v) for k, v in precos.items() if k in PrecoDoModelo.__annotations__}
            )
        except (TypeError, ValueError):
            continue
    return tabela


def precificar(
    uso: UsoDoAgente, *, modelo_padrao: str = "", tabela: dict[str, PrecoDoModelo] | None = None
) -> UsoDoAgente:
    """Calcula o custo de um uso que só trouxe tokens, se houver preço para o modelo.

    Idempotente: uso com custo informado pelo agente, já precificado ou sem tokens volta igual."""
    modelo = uso.modelo or modelo_padrao
    if uso.origem != ORIGEM_TOKENS:
        return uso if uso.modelo or not modelo else replace(uso, modelo=modelo)
    preco = (tabela if tabela is not None else tabela_do_ambiente()).get(modelo)
    if preco is None:
        return replace(uso, modelo=modelo)
    custo = (
        uso.tokens_entrada * preco.entrada
        + uso.tokens_saida * preco.saida
        + uso.tokens_cache_leitura * preco.cache_leitura
        + uso.tokens_cache_escrita * preco.cache_escrita
    ) / _POR_MILHAO
    return replace(uso, modelo=modelo, custo_usd=round(custo, 6), origem=ORIGEM_TABELA)
