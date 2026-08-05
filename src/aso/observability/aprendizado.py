"""Aprendizado da esteira (§24 do fluxo.md) — ADR-0025.

Puro: recebe dados já coletados e produz um relatório agregado. Não importa
`control` (regra de módulo: `observability` importa só `shared`) — quem coleta
o estado e monta a entrada é `OrchestrationService.get_learning_report`, no
mesmo arranjo de `next_step.py` (função pura) + `Service.next_step` (coleta),
e de `agent_log` (ADR-0015).

Até este incremento, `metrics.py`/`slo_report` eram só observacionais: nada
agregava por executor e nada realimentava decisão. Agora há insumo de verdade
— `card.failures` com categoria (ADR-0022), `card.executor` (ADR-0017),
rodadas de revisão (ADR-0017) — o que faltava quando o §24 foi adiado nos
planos anteriores.

**Limite deliberado**: o relatório NÃO realimenta decisão automaticamente. O
§24 diz que as informações "podem ser utilizadas" para melhorar decisões
futuras — permissivo, não imperativo. Fechar o laço agora significaria um
runtime que muda de perfil de executor sozinho com base em amostra pequena e
enviesada (as falhas observadas dependem só das demandas que apareceram).
`recomendacao` é texto para o operador ler, nunca um campo que outro código
consome para decidir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CardSnapshot:
    """O que o agregador precisa de cada card — já achatado pelo coletor, para
    este módulo não depender do tipo `KanbanCard` de `kanban/` nem de `control`."""

    id: str
    executor: str
    failures: list[dict[str, Any]] = field(default_factory=list)
    tempo_ms: float = 0.0
    # Consumo real (§1.1, ADR-0026) — `custo_usd` acumulado do card e se ele
    # informou uso em toda execução (`indisponivel` se nenhuma informou).
    custo_usd: float = 0.0
    uso_indisponivel: bool = True
    entregue: bool = False  # chegou a Done — denominador de `custo_por_entrega`


@dataclass(frozen=True)
class PullRequestSnapshot:
    card_id: str | None
    review_rounds: int
    review_status: str


@dataclass(frozen=True)
class DesempenhoPorExecutor:
    """Uma linha do §24: "quais modelos tiveram melhor desempenho"."""

    executor: str
    execucoes: int
    falhas: int
    retrabalho: int  # nº de reexecuções (uma por falha registrada)
    tempo_medio_ms: float
    rodadas_de_revisao_media: float
    erros_recorrentes: dict[str, int]  # categoria -> contagem
    # Custo real (§1.1/§1.3, ADR-0026) — nunca compare custo bruto entre executores
    # sem dividir por entrega: um executor caro que acerta de primeira pode sair
    # mais barato que um barato que precisa de três tentativas.
    custo_total_usd: float = 0.0
    custo_por_entrega: float = 0.0  # custo_total_usd / cards que chegaram a Done
    execucoes_sem_custo: int = 0  # quantas não informaram uso (não somadas como zero)


@dataclass(frozen=True)
class RelatorioDeAprendizado:
    orchestration_id: str
    total_cards: int
    total_falhas: int
    total_retrabalho: int
    intervencoes_humanas: int
    falhas_por_etapa: dict[str, int]
    erros_recorrentes: dict[str, int]
    desempenho_por_executor: list[DesempenhoPorExecutor]
    recomendacao: str = ""


def consolidar(
    orchestration_id: str,
    cards: list[CardSnapshot],
    pulls: list[PullRequestSnapshot],
    *,
    intervencoes_humanas: int = 0,
) -> RelatorioDeAprendizado:
    """Agrega por executor: execuções, falhas, retrabalho, tempo, rodadas,
    erros recorrentes. Sem cards, devolve um relatório vazio — sem divisão
    por zero em lugar nenhum."""
    if not cards:
        return RelatorioDeAprendizado(
            orchestration_id=orchestration_id,
            total_cards=0,
            total_falhas=0,
            total_retrabalho=0,
            intervencoes_humanas=intervencoes_humanas,
            falhas_por_etapa={},
            erros_recorrentes={},
            desempenho_por_executor=[],
        )
    por_executor: dict[str, list[CardSnapshot]] = {}
    for card in cards:
        chave = card.executor or "(sem executor)"
        por_executor.setdefault(chave, []).append(card)
    rounds_por_card = {p.card_id: p.review_rounds for p in pulls if p.card_id}

    desempenho: list[DesempenhoPorExecutor] = []
    erros_totais: dict[str, int] = {}
    falhas_por_etapa: dict[str, int] = {}
    total_falhas = 0
    for executor, seus_cards in sorted(por_executor.items()):
        falhas = sum(len(c.failures) for c in seus_cards)
        rounds = [rounds_por_card.get(c.id, 0) for c in seus_cards]
        tempos = [c.tempo_ms for c in seus_cards if c.tempo_ms]
        erros: dict[str, int] = {}
        for card in seus_cards:
            for falha in card.failures:
                categoria = str(falha.get("categoria") or "desconhecida")
                etapa = str(falha.get("etapa") or "desconhecida")
                erros[categoria] = erros.get(categoria, 0) + 1
                erros_totais[categoria] = erros_totais.get(categoria, 0) + 1
                falhas_por_etapa[etapa] = falhas_por_etapa.get(etapa, 0) + 1
        custo_total = round(sum(c.custo_usd for c in seus_cards), 6)
        entregas = sum(1 for c in seus_cards if c.entregue)
        desempenho.append(
            DesempenhoPorExecutor(
                executor=executor,
                execucoes=len(seus_cards),
                falhas=falhas,
                retrabalho=falhas,
                tempo_medio_ms=round(sum(tempos) / len(tempos), 2) if tempos else 0.0,
                rodadas_de_revisao_media=round(sum(rounds) / len(rounds), 2) if rounds else 0.0,
                erros_recorrentes=erros,
                custo_total_usd=custo_total,
                custo_por_entrega=round(custo_total / entregas, 6) if entregas else 0.0,
                execucoes_sem_custo=sum(1 for c in seus_cards if c.uso_indisponivel),
            )
        )
        total_falhas += falhas

    return RelatorioDeAprendizado(
        orchestration_id=orchestration_id,
        total_cards=len(cards),
        total_falhas=total_falhas,
        total_retrabalho=total_falhas,
        intervencoes_humanas=intervencoes_humanas,
        falhas_por_etapa=falhas_por_etapa,
        erros_recorrentes=erros_totais,
        desempenho_por_executor=desempenho,
        recomendacao=_recomendar(desempenho),
    )


def _recomendar(desempenho: list[DesempenhoPorExecutor]) -> str:
    """Texto informativo para o operador — nunca uma decisão automática (§24)."""
    com_execucao = [d for d in desempenho if d.execucoes]
    if not com_execucao:
        return ""
    pior = max(com_execucao, key=lambda d: d.falhas / d.execucoes)
    if pior.falhas == 0:
        return "Nenhuma falha registrada nesta amostra — sem padrão a apontar ainda."
    return (
        f"'{pior.executor}' teve {pior.falhas} falha(s) em {pior.execucoes} execução(ões) "
        "— considere revisar o perfil/effort antes da próxima demanda semelhante. "
        "Recomendação informativa: a escolha de executor continua manual (§9)."
    )
