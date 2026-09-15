"""AgentSupervisor — executa um agente sob supervisão (§15, AgentWrapper).

Tenta executar via ExecutionProvider; com `max_attempts > 1`, re-tenta anexando um `nudge`
(dica de correção) à tarefa. **Por padrão, uma tentativa só (ADR-0071):** quem decide se e
como re-tentar é o roteamento de falha do `run_card` (mesmo agente, mais esforço, outro
executor, ADR-0019). Duas camadas de retry sobrepostas multiplicavam execuções — cada uma com
worktree novo e timeout longo — e o supervisor re-tentava até timeout, que o roteamento
trataria de outro jeito. Esgotadas as tentativas, levanta `AgentExecutionError` com a
**mensagem original** (encadeada): o diagnóstico precisa do motivo real, não de
"falhou após N tentativas".
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
        max_attempts: int = 1,
        event_log: EventLog | None = None,
    ) -> None:
        self.provider: ExecutionProvider = provider or LocalMockExecutionProvider()
        self.max_attempts = max(1, max_attempts)
        self.event_log = event_log or EventLog()

    def run(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        current = dict(task)
        for attempt in range(1, self.max_attempts + 1):
            try:
                output = self.provider.execute(agent, current)
                if attempt > 1:
                    self.event_log.append(
                        "AgentRetrySucceeded", {"agent": agent.role, "attempt": attempt}
                    )
                return output
            except Exception as exc:  # noqa: BLE001 — supervisiona qualquer falha do provider
                if attempt == self.max_attempts:
                    if isinstance(exc, AgentExecutionError):
                        raise
                    raise AgentExecutionError(str(exc)) from exc
                self.event_log.append(
                    "AgentRetry",
                    {"agent": agent.role, "attempt": attempt, "error": str(exc)},
                )
                # Nudge: re-envia com uma dica de correção (§26A supports_nudge).
                current = {**current, "nudge": f"tentativa {attempt} falhou: {exc}"}
        raise AssertionError("inalcançável: o laço retorna ou relança")  # pragma: no cover
