"""`CandidateRaceService` — corrida de candidatos por card (§26A.6, ADR-0066).

MEL-32, passo 4b: extraída junto da execução; usa o claim, os freios e a montagem de tarefa
do `ExecutionService` e persiste as corridas no bundle.
"""

from __future__ import annotations

import threading
from typing import Any

from aso.agents.executor import ExecutionProvider
from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.application.execution import ExecutionService
from aso.execution.candidates import CandidateRunner
from aso.governance.models import CandidateRun
from aso.shared.ids import gen_id


class CandidateRaceService:
    """Roda candidatos em paralelo por card e registra a corrida (histórico auditável)."""

    def __init__(
        self, store: BundleStore, *, execution: ExecutionService, max_races_per_card: int
    ) -> None:
        self._bundle_store = store
        self._execution = execution
        self._max_races_per_card = max_races_per_card

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    # Freios, claim e montagem de tarefa vêm do ExecutionService (mesma regra de lock).
    def _build_task(self, *args: Any, **kwargs: Any) -> Any:
        return self._execution._build_task(*args, **kwargs)

    def _liberar_claim(self, *args: Any, **kwargs: Any) -> Any:
        return self._execution._liberar_claim(*args, **kwargs)

    def _recusar_se_estrategia_pendente(self, *args: Any, **kwargs: Any) -> Any:
        return self._execution._recusar_se_estrategia_pendente(*args, **kwargs)

    def _recusar_se_orcamento_estourado(self, *args: Any, **kwargs: Any) -> Any:
        return self._execution._recusar_se_orcamento_estourado(*args, **kwargs)

    def _reivindicar_card(self, *args: Any, **kwargs: Any) -> Any:
        return self._execution._reivindicar_card(*args, **kwargs)

    def race_card(
        self, orchestration_id: str, card_id: str, providers: list[ExecutionProvider]
    ) -> dict[str, object]:
        """Roda múltiplos agentes CLI em paralelo por card e compara os diffs (§26A.6).

        Reserva o lease do card durante a corrida (ADR-0058) sem mudar a coluna: a
        corrida compara candidatos, não é a execução do card — mas não pode disputar o
        mesmo card com um `run_card` concorrente.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            self._recusar_se_estrategia_pendente(b)
            self._recusar_se_orcamento_estourado(b)
            card = b.board_service.get_card(card_id)
            if card is None or card.assignee is None:
                raise KeyError(f"Card inválido: {card_id}")
            agent = b.agent_registry.get(card.assignee)
            if agent is None:
                raise KeyError(f"Agente não registrado: {card.assignee}")
            self._reivindicar_card(b, card, execution_id=gen_id("race"), mover=False)
        try:
            candidates = CandidateRunner().run(agent, self._build_task(b, card, agent), providers)
        finally:
            with self._lock_for(orchestration_id):
                self._liberar_claim(card)
                self._persist(b)
        comparison = CandidateRunner.compare(candidates)
        with self._lock_for(orchestration_id):
            # Persiste a corrida como entidade rastreável (histórico auditável §26A.6/§21).
            run = CandidateRun(
                orchestration_id=orchestration_id,
                card_id=card_id,
                recommended_branch=comparison["recommended_branch"],
                candidates=list(comparison["candidates"]),
            )
            b.candidate_runs.append(run)
            self._prune_races(b, card_id)
            b.event_log.append(
                "CandidatesEvaluated",
                {
                    "run_id": run.id,
                    "card_id": card_id,
                    "count": len(candidates),
                    "recommended": comparison["recommended_branch"],
                },
            )
            # Candidato perdido nunca é silencioso (plano6 §0/ADR-0024): um evento por
            # falha, rastreável mesmo depois que o ring de corridas descartar `run`.
            falhas = comparison["falhas"]
            for falha in falhas:
                b.event_log.append(
                    "CandidateFailed",
                    {"run_id": run.id, "card_id": card_id, **falha},
                )
            self._persist(b)
        comparison["run_id"] = run.id
        return comparison

    def _prune_races(self, b: OrchestrationBundle, card_id: str) -> None:
        """Mantém apenas as N corridas mais recentes por card (retenção §26A.6)."""
        same = [r for r in b.candidate_runs if r.card_id == card_id]
        if len(same) <= self._max_races_per_card:
            return
        drop = {r.id for r in same[: len(same) - self._max_races_per_card]}
        b.candidate_runs[:] = [r for r in b.candidate_runs if r.id not in drop]
