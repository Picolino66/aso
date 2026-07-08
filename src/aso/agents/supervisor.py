"""AgentSupervisor — executa um agente com retry e nudge (§15, AgentWrapper).

Tenta executar via ExecutionProvider; em caso de falha, re-tenta anexando um
`nudge` (dica de correção) à tarefa, até `max_attempts`. Esgotadas as tentativas,
levanta `AgentExecutionError`.
"""

from __future__ import annotations

from typing import Any

from aso.agents.executor import AgentExecutionError, ExecutionProvider, LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.shared.events import EventLog


class AgentSupervisor:
    def __init__(
        self,
        provider: ExecutionProvider | None = None,
        *,
        max_attempts: int = 2,
        event_log: EventLog | None = None,
    ) -> None:
        self.provider: ExecutionProvider = provider or LocalMockExecutionProvider()
        self.max_attempts = max_attempts
        self.event_log = event_log or EventLog()

    def run(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        current = dict(task)
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                output = self.provider.execute(agent, current)
                if attempt > 1:
                    self.event_log.append(
                        "AgentRetrySucceeded", {"agent": agent.role, "attempt": attempt}
                    )
                return output
            except Exception as exc:  # noqa: BLE001 — supervisiona qualquer falha do provider
                last_error = exc
                self.event_log.append(
                    "AgentRetry",
                    {"agent": agent.role, "attempt": attempt, "error": str(exc)},
                )
                # Nudge: re-envia com uma dica de correção (§26A supports_nudge).
                current = {**current, "nudge": f"tentativa {attempt} falhou: {exc}"}
        raise AgentExecutionError(
            f"{agent.role} falhou após {self.max_attempts} tentativas: {last_error}"
        )
