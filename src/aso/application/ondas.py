"""Coordenador de ondas: cards independentes em paralelo, com limite (ADR-0074, MEL-50).

`run_phase` executava os cards em sequência e `run_plan` tinha um laço próprio de ondas (sem o
roteamento de falha do `run_card`); a estratégia `parallel_agents` do motor de decisão não mudava
nada. Aqui fica o único caminho de execução em lote:

- **onda** = cards `Ready` cuja(s) dependência(s) já estão `Done`; card com dependência pendente
  não entra (fica em `aguardando_dependencia`, sem ser bloqueado por uma execução às cegas);
- cada card roda pelo `run_card` — claim (ADR-0058), retry pelo roteamento (ADR-0071), freios;
- paralelismo por orquestração: `parallel_agents` usa `ASO_MAX_PARALELO_POR_ORQUESTRACAO`
  (padrão 2); as demais estratégias executam um card por vez;
- limite global de execuções simultâneas no processo: `ASO_MAX_EXECUCOES_SIMULTANEAS` (padrão 4).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import Any

from aso.application.bundles import BundleStore
from aso.execution.jobs import JobCancelado, verificar_cancelamento
from aso.kanban.models import KanbanCard
from aso.shared.types import ColumnKey, ExecutionStrategy


def _inteiro_do_ambiente(variavel: str, padrao: int) -> int:
    try:
        return max(1, int(os.environ.get(variavel, padrao)))
    except ValueError:
        return padrao


_SEMAFORO_GLOBAL = threading.BoundedSemaphore(
    _inteiro_do_ambiente("ASO_MAX_EXECUCOES_SIMULTANEAS", 4)
)


def limite_da_estrategia(estrategia: ExecutionStrategy | str) -> int:
    """`parallel_agents` roda até o limite configurado; qualquer outra, um card por vez."""
    if str(estrategia) == ExecutionStrategy.PARALLEL.value:
        return _inteiro_do_ambiente("ASO_MAX_PARALELO_POR_ORQUESTRACAO", 2)
    return 1


@dataclass
class ResultadoDasOndas:
    executados: list[str] = field(default_factory=list)
    falhos: list[str] = field(default_factory=list)
    aguardando_dependencia: list[str] = field(default_factory=list)
    em_execucao: list[str] = field(default_factory=list)
    ondas: int = 0
    paralelismo: int = 1


class CoordenadorDeOndas:
    def __init__(self, store: BundleStore, *, run_card: Callable[..., Any]) -> None:
        self._bundle_store = store
        self._run_card = run_card

    @staticmethod
    def _dependencias_prontas(cards: dict[str, KanbanCard], card: KanbanCard) -> bool:
        return all(
            (dep := cards.get(dep_id)) is None or dep.status == ColumnKey.DONE
            for dep_id in card.dependencies
        )

    def executar(
        self,
        orchestration_id: str,
        card_ids: list[str],
        *,
        limite: int,
        provider: Any = None,
        effort: str | None = None,
    ) -> ResultadoDasOndas:
        resultado = ResultadoDasOndas(paralelismo=max(1, limite))
        pendentes = list(card_ids)
        while pendentes:
            verificar_cancelamento()  # job cancelado: nenhuma onda nova (ADR-0067)
            b = self._bundle_store.get(orchestration_id)
            cards = {c.id: c for c in b.board_service.cards_of(b.board.id)}
            onda: list[str] = []
            for cid in pendentes:
                card = cards.get(cid)
                if card is None or card.status != ColumnKey.READY:
                    continue
                if card.em_execucao_desde:
                    resultado.em_execucao.append(cid)  # outro caminho já reivindicou (ADR-0058)
                elif self._dependencias_prontas(cards, card):
                    onda.append(cid)
            restantes = [
                cid for cid in pendentes if cid not in onda and cid not in resultado.em_execucao
            ]
            if not onda:
                resultado.aguardando_dependencia = [
                    cid
                    for cid in restantes
                    if cards.get(cid) and cards[cid].status == ColumnKey.READY
                ]
                break
            self._executar_onda(orchestration_id, onda, resultado, provider=provider, effort=effort)
            resultado.ondas += 1
            pendentes = restantes
        return resultado

    def _executar_onda(
        self,
        orchestration_id: str,
        onda: list[str],
        resultado: ResultadoDasOndas,
        *,
        provider: Any,
        effort: str | None,
    ) -> None:
        def _um(cid: str) -> tuple[str, bool]:
            with _SEMAFORO_GLOBAL:
                verificar_cancelamento()
                try:
                    self._run_card(orchestration_id, cid, provider=provider, effort=effort)
                except Exception:  # noqa: BLE001 — card inválido não derruba a onda inteira
                    return cid, False
            card = self._bundle_store.get(orchestration_id).board_service.get_card(cid)
            return cid, not (card is None or card.status == ColumnKey.FAILED)

        with ThreadPoolExecutor(max_workers=min(resultado.paralelismo, len(onda))) as pool:
            # Um contexto copiado por card: cancelamento do job e request_id chegam às threads.
            futuros = [pool.submit(copy_context().run, _um, cid) for cid in onda]
            cancelado: JobCancelado | None = None
            for futuro in futuros:
                try:
                    cid, ok = futuro.result()
                except JobCancelado as exc:
                    cancelado = exc
                    continue
                (resultado.executados if ok else resultado.falhos).append(cid)
            if cancelado is not None:
                raise cancelado
