"""Escolha automática de esforço (§9 do fluxo.md) — ADR-0022.

Puro e determinístico: dado a mesma complexidade e o mesmo risco, a sugestão é
sempre a mesma — tabela, não palpite de agente. `DemandBrief.complexidade` é
coletada desde o Incremento A (ADR-0016) e nunca foi lida por ninguém; isto é o
que a torna útil.
"""

from __future__ import annotations

from aso.shared.types import RiskLevel

# Sentinela: "o degrau mais alto que o perfil do executor aceitar" — só o catálogo
# sabe o que um perfil suporta, então a tabela devolve o sentinela e quem tem o
# catálogo em mãos (`OrchestrationService`) resolve com `resolver_topo`.
EFFORT_TOPO = "topo"

# complexidade -> (esforço p/ risco low|medium, esforço p/ risco high|critical).
_TABELA: dict[str, tuple[str, str]] = {
    "simples": ("low", "medium"),
    "intermediaria": ("medium", "high"),
    "complexa": ("high", "high"),
    "estrategica": ("high", EFFORT_TOPO),
}

# Complexidade fora do vocabulário conhecido (ficha antiga/heurística) cai aqui —
# nunca lança, nunca subestima uma demanda de risco alto.
_PADRAO = ("medium", "high")


def sugerir_effort(complexidade: str, risco: RiskLevel) -> str:
    """§9: complexidade e risco decidem o esforço — tabela, não palpite."""
    risco_alto = risco in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    baixo, alto = _TABELA.get(complexidade, _PADRAO)
    return alto if risco_alto else baixo


def resolver_topo(sugestao: str, suportados: list[str]) -> str:
    """Resolve o sentinela `EFFORT_TOPO` para o degrau mais alto aceito pelo perfil.

    `supported_efforts` (ver `execution/catalog.py`) vem do menor para o maior
    esforço — o último item é o topo. Sem lista (perfil não-gerenciado), "high" é
    o topo do vocabulário padrão low/medium/high.
    """
    if sugestao != EFFORT_TOPO:
        return sugestao
    return suportados[-1] if suportados else "high"
