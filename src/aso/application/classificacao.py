"""`ClassificationService` — reclassificação humana, replanejamento e duplicação (ADR-0066).

MEL-32, passo 11d: complementa o `IntakeService` (criação e triagem) com o que acontece depois
da triagem: o humano corrige a ficha, o plano ainda intocado é refeito e a demanda pode ser
duplicada pelo mesmo caminho de criação.
"""

from __future__ import annotations

import threading
from typing import Any

from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.application.intake import IntakeService
from aso.application.preparation import prioridade_de
from aso.control.decision_engine import MultiAgentDecisionEngine
from aso.control.execution_planner import ExecutionPlanner
from aso.control.models import Orchestration
from aso.control.triage import DemandBrief
from aso.shared.ids import now_iso
from aso.shared.types import ColumnKey, RiskLevel


class ClassificationService:
    """Edição humana da classificação, replanejamento de plano intocado e duplicação."""

    def __init__(self, store: BundleStore, *, intake: IntakeService) -> None:
        self._bundle_store = store
        self._intake = intake

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    def get(self, orchestration_id: str) -> Orchestration:
        return self._bundle(orchestration_id).orchestration

    def create_with_triage(self, *args: Any, **kwargs: Any) -> Orchestration:
        return self._intake.create_with_triage(*args, **kwargs)

    def _apply_routing_rule(self, *args: Any, **kwargs: Any) -> Any:
        return self._intake._apply_routing_rule(*args, **kwargs)

    def duplicate_orchestration(
        self, orchestration_id: str, *, actor: str = "system"
    ) -> Orchestration:
        """Duplicar (Tela 02, wf §4.4, ADR-0038): cria uma orquestração NOVA a
        partir do `user_request`/projeto/execução da origem, re-triada do zero
        pelo mesmo caminho de `create_with_triage` ("o único caminho correto de
        criação", ADR-0017) — não é uma cópia de estado: cards, histórico e
        `demand_brief` não são clonados, a nova orquestração começa do zero,
        como qualquer outra."""
        origem = self.get(orchestration_id)
        nova = self.create_with_triage(
            origem.user_request,
            project_id=origem.project_id,
            target_path=origem.target_path,
            execution_mode=origem.execution_mode,
            executor=origem.selected_executor,
            effort=origem.selected_effort,
            validation_command=origem.validation_command,
        )
        with self._lock_for(nova.id):
            b = self._bundle(nova.id)
            b.event_log.append(
                "OrchestrationDuplicated", {"origem_id": orchestration_id, "actor": actor}
            )
            self._persist(b)
        return nova

    def update_classification(
        self,
        orchestration_id: str,
        *,
        tipo: str | None = None,
        risco: RiskLevel | None = None,
        complexidade: str | None = None,
        impactos: list[str] | None = None,
        dominios: list[str] | None = None,
        actor: str = "system",
    ) -> DemandBrief:
        """Edição pontual da classificação (Tela 05, wf §7, ADR-0044) — diferente de
        `set_demand_brief`/`retriage_demand` (reescrita completa via nova triagem),
        aqui só os campos informados mudam, com evento auditável antes/depois (mesmo
        padrão de `update_execution_settings`). Não há campo "prioridade" próprio de
        demanda — `risco` já cumpre esse papel (`prioridade_de`, sem esta ADR)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            before = {
                "tipo": brief.tipo,
                "risco": brief.risco,
                "complexidade": brief.complexidade,
                "impactos": list(brief.impactos),
                "dominios": list(brief.dominios),
            }
            if tipo is not None:
                brief.tipo = tipo
            if risco is not None:
                brief.risco = risco
            if complexidade is not None:
                brief.complexidade = complexidade
            if impactos is not None:
                brief.impactos = impactos
            if dominios is not None:
                brief.dominios = dominios
            b.orchestration.demand_brief = brief.model_dump(mode="json")
            b.orchestration.updated_at = now_iso()
            after = {
                "tipo": brief.tipo,
                "risco": brief.risco,
                "complexidade": brief.complexidade,
                "impactos": list(brief.impactos),
                "dominios": list(brief.dominios),
            }
            b.event_log.append(
                "ClassificationUpdated",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "before": before,
                    "after": after,
                },
            )
            self._persist(b)
            return brief

    def _replan_if_untouched(
        self, orchestration_id: str, brief: DemandBrief, *, actor: str
    ) -> tuple[bool, str]:
        """Recomputa o `ExecutionPlan` a partir da ficha re-triada — só enquanto nenhum
        card saiu de Ready. Depois de executado, replanejar mentiria sobre o trabalho
        já feito (mesma razão de `_validate_assignment_key` recusar reconfigurar uma
        fase que já ficou para trás). Devolve `(replanejou, motivo)`.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            cards = b.board_service.cards_of(b.board.id)
            if any(c.status != ColumnKey.READY for c in cards):
                motivo = (
                    "cards já saíram de Ready: replanejar agora reescreveria trabalho em andamento"
                )
                b.event_log.append(
                    "ReplanSkipped",
                    {"orchestration_id": orchestration_id, "actor": actor, "reason": motivo},
                )
                self._persist(b)
                return False, motivo
            planner = ExecutionPlanner(MultiAgentDecisionEngine())
            din = brief.to_decision_input(b.orchestration.user_request)
            novo_plano = planner.plan(orchestration_id, b.orchestration.execution_mode, din)
            self._apply_routing_rule(
                b.orchestration,
                din,
                novo_plano,
                executor_explicito=b.orchestration.selected_executor,
                effort_explicito=b.orchestration.selected_effort,
            )
            b.plan = novo_plano
            nova_prioridade = prioridade_de(brief)
            for card in cards:
                card.priority = nova_prioridade
            b.event_log.append(
                "Replanned",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "strategy": novo_plano.strategy.value,
                    "cards_repriced": len(cards),
                },
            )
            self._persist(b)
            return True, ""
