"""Orçamento com freio (§1.2/§3.2 do plano7.md) — ADR-0026.

Sem custo real capturado (ADR-0026, `shared/agent_usage.py`), o roteamento de falha
(ADR-0019) escalava effort/executor sem teto de gasto — o comportamento é correto e
foi pedido, mas com agentes reais é dinheiro saindo enquanto ninguém olha. Este módulo
é a função pura que decide "estourou?"; quem consulta o gasto acumulado e aplica o
freio (recusar nova execução, transformar escalada em `escalar_humano`) é
`OrchestrationService`, o único lugar autorizado a juntar orçamento + roteamento.
"""

from __future__ import annotations

SITUACAO_OK = "ok"
SITUACAO_ALERTA = "alerta"
SITUACAO_ESTOURADO = "estourado"

# A partir de quanto do teto o operador já deveria estar de olho, antes do bloqueio.
_LIMIAR_ALERTA = 0.8


def avaliar_orcamento(gasto_usd: float, teto_usd: float | None) -> tuple[str, str]:
    """Devolve (situação, motivo). Sem teto configurado (`None` ou ≤ 0), a orquestração
    se comporta como antes deste incremento: sempre `ok`, sem alerta nem bloqueio —
    orçamento é opt-in, não uma trava nova imposta a toda orquestração existente."""
    if teto_usd is None or teto_usd <= 0:
        return SITUACAO_OK, "sem teto configurado"
    if gasto_usd >= teto_usd:
        return (
            SITUACAO_ESTOURADO,
            f"gasto de US$ {gasto_usd:.2f} atingiu ou passou o teto de US$ {teto_usd:.2f}",
        )
    if gasto_usd >= teto_usd * _LIMIAR_ALERTA:
        return (
            SITUACAO_ALERTA,
            f"gasto de US$ {gasto_usd:.2f} já passou de {_LIMIAR_ALERTA:.0%} "
            f"do teto de US$ {teto_usd:.2f}",
        )
    return SITUACAO_OK, f"gasto de US$ {gasto_usd:.2f} dentro do teto de US$ {teto_usd:.2f}"
