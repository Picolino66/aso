"""Porta de consumo do agente: tokens e custo, quando o CLI os informa (§26A.11, ADR-0026).

Mesma solução da ADR-0015 (`shared/agent_output.py`), pelo mesmo motivo — `execution`
(quem produz o dado, em `agent_stream.extrair_uso`) não pode importar `observability`
(quem consome, em `aprendizado.py`); a porta fica em `shared`, e `control` faz a fiação
entre os dois (mesmo arranjo de `OutputSink`/`OutputBus`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Origem do dado: distingue "o CLI não informou" de "informou e o custo é zero" — um
# `UsoDoAgente()` default (todos os campos zerados) nunca deve ser lido como "grátis".
ORIGEM_AGENTE = "agente"
ORIGEM_INDISPONIVEL = "indisponivel"


@dataclass(frozen=True)
class UsoDoAgente:
    """Consumo relatado pelo próprio CLI — tokens e custo, quando disponíveis."""

    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_cache_leitura: int = 0
    tokens_cache_escrita: int = 0
    custo_usd: float = 0.0
    modelo: str = ""
    origem: str = ORIGEM_INDISPONIVEL


def acumular_uso(atual: dict[str, Any], novo: UsoDoAgente) -> dict[str, Any]:
    """Soma `novo` ao total já acumulado no card (`card.uso`, JSONB) — reexecuções
    somam, não substituem. `execucoes_sem_custo` conta separadamente das que
    informaram (§26A.11): uma execução sem uso informado nunca soma zero ao custo
    como se tivesse sido gratuita, mas o total de execuções continua correto."""
    sem_custo = int(atual.get("execucoes_sem_custo", 0))
    if novo.origem != ORIGEM_AGENTE:
        sem_custo += 1
    return {
        "tokens_entrada": int(atual.get("tokens_entrada", 0)) + novo.tokens_entrada,
        "tokens_saida": int(atual.get("tokens_saida", 0)) + novo.tokens_saida,
        "tokens_cache_leitura": int(atual.get("tokens_cache_leitura", 0))
        + novo.tokens_cache_leitura,
        "tokens_cache_escrita": int(atual.get("tokens_cache_escrita", 0))
        + novo.tokens_cache_escrita,
        "custo_usd": round(float(atual.get("custo_usd", 0.0)) + novo.custo_usd, 6),
        "modelo": novo.modelo or str(atual.get("modelo", "")),
        "execucoes": int(atual.get("execucoes", 0)) + 1,
        "execucoes_sem_custo": sem_custo,
    }
