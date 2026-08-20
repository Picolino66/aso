"""QualityGateEngine (§22).

Avalia critérios objetivos por fase sobre o OrchestratorContext. Gate falho
bloqueia o avanço de fase. Cada critério é um predicado sobre o payload do contexto.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aso.governance.models import GateCriterionResult, QualityGateResult
from aso.shared.events import EventLog
from aso.shared.types import GateStatus, Phase

# Um predicado recebe o payload do contexto e devolve (ok, evidência).
Predicate = Callable[[dict[str, Any]], tuple[bool, str]]


@dataclass
class Criterion:
    """Critério de um quality gate."""

    name: str
    predicate: Predicate
    blocking: bool = True


@dataclass
class GateDefinition:
    """Conjunto de critérios que compõem o gate de uma fase."""

    phase: Phase
    criteria: list[Criterion] = field(default_factory=list)


class QualityGateEngine:
    """Registra e executa quality gates por fase."""

    def __init__(self, event_log: EventLog | None = None) -> None:
        self._gates: dict[Phase, GateDefinition] = {}
        self.event_log = event_log or EventLog()

    def register(self, phase: Phase, criteria: list[Criterion]) -> None:
        self._gates[phase] = GateDefinition(phase=phase, criteria=criteria)

    def run(
        self, phase: Phase, orchestration_id: str, context: dict[str, Any]
    ) -> QualityGateResult:
        gate = self._gates.get(phase)
        if gate is None:
            raise KeyError(f"Nenhum quality gate registrado para a fase {phase.value}.")

        results: list[GateCriterionResult] = []
        blocking_issues: list[str] = []
        warnings: list[str] = []

        for crit in gate.criteria:
            inicio = time.monotonic()
            ok, evidence = crit.predicate(context)
            # Duração real (Tela 16, wf §18.2, ADR-0048) — mede o predicado inteiro,
            # inclusive quando ele roda um comando externo (validate_gate_command);
            # predicados em memória ficam com um valor pequeno real, não zero fabricado.
            duracao_ms = (time.monotonic() - inicio) * 1000
            status = GateStatus.PASSED if ok else GateStatus.FAILED
            results.append(
                GateCriterionResult(
                    name=crit.name,
                    status=status,
                    evidence=[evidence] if evidence else [],
                    failure_reason=None if ok else evidence,
                    duration_ms=duracao_ms,
                )
            )
            if not ok:
                if crit.blocking:
                    blocking_issues.append(crit.name)
                else:
                    warnings.append(crit.name)

        status = GateStatus.PASSED if not blocking_issues else GateStatus.FAILED
        result = QualityGateResult(
            orchestration_id=orchestration_id,
            phase=phase,
            status=status,
            criteria=results,
            blocking_issues=blocking_issues,
            warnings=warnings,
            approved_by="QualityGateEngine" if status == GateStatus.PASSED else None,
        )
        self.event_log.append(
            "QualityGateEvaluated",
            {"phase": phase.value, "status": status.value, "blocking": blocking_issues},
        )
        return result
