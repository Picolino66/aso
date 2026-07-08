"""MetricsService + avaliação de SLOs (F7 — observability-engine).

Calcula métricas operacionais a partir do OrchestrationService (consultas indexadas
e timeline) e avalia SLOs baseados em sintomas (§F7): conflitos abertos, cards
bloqueados e cobertura de snapshot.
"""

from __future__ import annotations

import os
from typing import Any

from aso.control.orchestration_service import OrchestrationService

# SLOs padrão (baseados em sintomas). Cada um é avaliado por orquestração.
_BLOCKED_STATUSES = ("Blocked", "Failed")


def _failure_budget() -> float:
    """Orçamento de erro (fração tolerável de execuções que podem falhar)."""
    try:
        return max(1e-6, float(os.environ.get("ASO_SLO_FAILURE_BUDGET", "0.10")))
    except ValueError:
        return 0.10


def _severity(consumed_pct: float) -> str:
    """Severidade por consumo do orçamento de erro (burn-rate)."""
    if consumed_pct >= 100:
        return "critical"
    if consumed_pct >= 50:
        return "warning"
    return "ok"


class MetricsService:
    """Métricas RED-like e SLOs derivados do estado das orquestrações."""

    def __init__(self, service: OrchestrationService) -> None:
        self.svc = service

    def orchestration_metrics(self, orchestration_id: str) -> dict[str, Any]:
        counts = self.svc.count_cards_by_status(orchestration_id)
        open_conflicts = [c for c in self.svc.conflicts(orchestration_id) if c.status == "open"]
        return {
            "orchestration_id": orchestration_id,
            "phase": self.svc.get(orchestration_id).current_phase.value,
            "snapshot_version": self.svc.get(orchestration_id).snapshot_version,
            "cards_by_status": counts,
            "cards_total": sum(counts.values()),
            "adrs_total": len(self.svc.list_adrs(orchestration_id)),
            "snapshots_total": len(self.svc.list_snapshots(orchestration_id)),
            "open_conflicts": len(open_conflicts),
            "events_total": len(self.svc.timeline(orchestration_id)),
        }

    def global_metrics(self) -> dict[str, Any]:
        # Agregação direta no repositório (COUNT/GROUP BY), sem hidratar aggregates.
        return self.svc.aggregate_metrics()

    def execution_metrics(self, orchestration_id: str) -> dict[str, Any]:
        """Métricas de execução: nº de execuções, duração média, retries, falhas, waiting-human."""
        events = self.svc.timeline(orchestration_id)
        executed = [e for e in events if e.type == "AgentExecuted"]
        durations = [float(e.payload.get("ms", 0)) for e in executed]
        counts = self.svc.count_cards_by_status(orchestration_id)
        return {
            "orchestration_id": orchestration_id,
            "agent_executions": len(executed),
            "avg_ms": round(sum(durations) / len(durations), 1) if durations else 0.0,
            "retries": len([e for e in events if e.type == "AgentRetry"]),
            "failures": len([e for e in events if e.type == "AgentFailed"]),
            "waiting_human": counts.get("WaitingHuman", 0),
        }

    def execution_timeline(self, orchestration_id: str) -> dict[str, Any]:
        """Timeline de custo por card (F7): execuções, tempo acumulado, falhas por card.

        O custo é aproximado pelo tempo de execução (ms) agregado a partir dos eventos
        `AgentExecuted`, permitindo ver onde o esforço dos agentes se concentra.
        """
        events = self.svc.timeline(orchestration_id)
        by_card: dict[str, dict[str, Any]] = {}
        for e in events:
            if e.type != "AgentExecuted":
                continue
            cid = str(e.payload.get("card_id") or "—")
            entry = by_card.setdefault(
                cid,
                {"card_id": cid, "executions": 0, "total_ms": 0.0, "failures": 0, "runs": []},
            )
            ms = float(e.payload.get("ms", 0))
            ok = bool(e.payload.get("ok", True))
            entry["executions"] += 1
            entry["total_ms"] = round(entry["total_ms"] + ms, 1)
            if not ok:
                entry["failures"] += 1
            entry["runs"].append(
                {"agent": e.payload.get("agent"), "ms": ms, "ok": ok, "at": e.created_at}
            )
        cards = sorted(by_card.values(), key=lambda c: -c["total_ms"])
        for c in cards:
            c["avg_ms"] = round(c["total_ms"] / c["executions"], 1) if c["executions"] else 0.0
        return {
            "orchestration_id": orchestration_id,
            "cards": cards,
            "total_ms": round(sum(c["total_ms"] for c in cards), 1),
            "executions_total": sum(c["executions"] for c in cards),
        }

    def prometheus(self) -> str:
        """Métricas globais no formato de exposição Prometheus (text/plain)."""
        g = self.global_metrics()
        lines = [
            "# HELP aso_orchestrations_total Total de orquestrações",
            "# TYPE aso_orchestrations_total gauge",
            f"aso_orchestrations_total {g['orchestrations_total']}",
            "# HELP aso_open_conflicts_total Conflitos abertos",
            "# TYPE aso_open_conflicts_total gauge",
            f"aso_open_conflicts_total {g['open_conflicts']}",
            "# HELP aso_adrs_total Total de ADRs",
            "# TYPE aso_adrs_total gauge",
            f"aso_adrs_total {g['adrs_total']}",
            "# HELP aso_snapshots_total Total de snapshots",
            "# TYPE aso_snapshots_total gauge",
            f"aso_snapshots_total {g['snapshots_total']}",
            "# HELP aso_agent_retries_total Total de retries de agentes",
            "# TYPE aso_agent_retries_total counter",
            f"aso_agent_retries_total {g.get('agent_retries', 0)}",
            "# HELP aso_agent_failures_total Total de falhas terminais de agentes",
            "# TYPE aso_agent_failures_total counter",
            f"aso_agent_failures_total {g.get('agent_failures', 0)}",
            "# HELP aso_cards Total de cards por status",
            "# TYPE aso_cards gauge",
        ]
        for status, count in sorted(g["cards_by_status"].items()):
            lines.append(f'aso_cards{{status="{status}"}} {count}')
        return "\n".join(lines) + "\n"

    def _symptom_slo(self, name: str, target: Any, actual: Any, ok: bool) -> dict[str, Any]:
        """SLO de sintoma (estrito): sem orçamento — qualquer desvio é crítico."""
        consumed = 0.0 if ok else 100.0
        return {
            "name": name,
            "target": target,
            "actual": actual,
            "ok": ok,
            "budget": 0,
            "consumed_pct": consumed,
            "burn_rate": 0.0 if ok else 1.0,
            "severity": _severity(consumed),
        }

    def _failure_trend(self, executed: list[Any]) -> str:
        """Tendência da taxa de falhas: compara a 1ª e a 2ª metade das execuções."""
        if len(executed) < 4:
            return "stable"
        mid = len(executed) // 2

        def rate(evs: list[Any]) -> float:
            return sum(1 for e in evs if not e.payload.get("ok", True)) / len(evs) if evs else 0.0

        first, second = rate(executed[:mid]), rate(executed[mid:])
        if second > first + 0.05:
            return "rising"
        if second < first - 0.05:
            return "falling"
        return "stable"

    def slo_report(self, orchestration_id: str) -> dict[str, Any]:
        counts = self.svc.count_cards_by_status(orchestration_id)
        conflicts = self.svc.conflicts(orchestration_id)
        open_conflicts = len([c for c in conflicts if c.status == "open"])
        blocked = sum(counts.get(s, 0) for s in _BLOCKED_STATUSES)
        snapshot = self.svc.get(orchestration_id).snapshot_version

        slos = [
            self._symptom_slo("sem_conflitos_abertos", 0, open_conflicts, open_conflicts == 0),
            self._symptom_slo("sem_cards_bloqueados", 0, blocked, blocked == 0),
            self._symptom_slo("snapshot_da_fase_gerado", "!= O0", snapshot, snapshot != "O0"),
        ]

        # Error budget da taxa de falhas de execução (SLI de taxa, com burn-rate real).
        events = self.svc.timeline(orchestration_id)
        executed = [e for e in events if e.type == "AgentExecuted"]
        failures = sum(1 for e in executed if not e.payload.get("ok", True))
        n = len(executed)
        fail_rate = failures / n if n else 0.0
        budget = _failure_budget()
        consumed_pct = round(100 * fail_rate / budget, 1)
        error_budget = {
            "sli": "taxa_de_falhas_de_execucao",
            "executions": n,
            "failures": failures,
            "fail_rate": round(fail_rate, 4),
            "budget": budget,
            "consumed_pct": consumed_pct,
            "burn_rate": round(fail_rate / budget, 3),
            "trend": self._failure_trend(executed),
            "severity": _severity(consumed_pct),
        }

        breaches = [s["name"] for s in slos if not s["ok"]]
        if error_budget["severity"] == "critical":
            breaches.append(error_budget["sli"])

        # Alertas com severidade (§F7 — alertas por SLO breach / burn-rate).
        alerts: list[dict[str, Any]] = []
        for s in slos:
            if s["severity"] != "ok":
                alerts.append(
                    {
                        "slo": s["name"],
                        "severity": "high" if s["severity"] == "critical" else "medium",
                        "message": f"SLO '{s['name']}' violado (atual={s['actual']}).",
                    }
                )
        if error_budget["severity"] != "ok":
            alerts.append(
                {
                    "slo": error_budget["sli"],
                    "severity": "high" if error_budget["severity"] == "critical" else "medium",
                    "message": (
                        f"Orçamento de erro em {consumed_pct}% "
                        f"(taxa {error_budget['fail_rate']}, tendência {error_budget['trend']})."
                    ),
                }
            )

        return {
            "orchestration_id": orchestration_id,
            "slos": slos,
            "breaches": breaches,
            "error_budget": error_budget,
            "alerts": alerts,
        }
