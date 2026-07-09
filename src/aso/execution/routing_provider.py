"""RoutingExecutionProvider — escolhe o executor por fase (autopilot M5).

Roteia a execução conforme a fase da tarefa: fases de planejamento (F1–F4) vão
para o "planner" (tipicamente um LlmExecutionProvider) e fases de código (F5–F6)
para o "coder" (tipicamente um agente CLI em worktree). Se só um estiver
configurado, ele atende todas as fases.
"""

from __future__ import annotations

from typing import Any

from aso.agents.executor import ExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec

_CODE_PHASES = ("F5", "F6")


class RoutingExecutionProvider:
    """Encaminha `execute` ao provider adequado à fase da tarefa."""

    def __init__(
        self,
        *,
        planner: ExecutionProvider | None = None,
        coder: ExecutionProvider | None = None,
        code_phases: tuple[str, ...] = _CODE_PHASES,
    ) -> None:
        if planner is None and coder is None:
            raise ValueError("RoutingExecutionProvider exige ao menos um provider (planner/coder).")
        self.id = "router"
        self._planner = planner
        self._coder = coder
        self._code_phases = code_phases

    def _pick(self, phase: str) -> ExecutionProvider:
        is_code = phase in self._code_phases
        # Preferência por fase, com fallback para o que estiver disponível.
        primary = self._coder if is_code else self._planner
        return primary or self._coder or self._planner  # type: ignore[return-value]

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        return self._pick(str(task.get("phase", "F5"))).execute(agent, task)
