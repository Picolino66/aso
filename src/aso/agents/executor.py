"""ExecutionProvider + AgentExecutor (§26, §43, TASK-08).

Define a porta `ExecutionProvider` (abstrata) e o `LocalMockExecutionProvider`
(§43: implementar mock antes de provider real). O `AgentExecutor` roda um agente
através de um provider e retorna uma `AgentOutput` estruturada com patches propostos.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from aso.agents.models import AgentOutput, AgentSpec
from aso.governance.models import ContextPatch
from aso.shared.events import EventLog
from aso.shared.types import PatchType, Phase


class AgentExecutionError(RuntimeError):
    """Falha terminal de execução de um agente (após esgotar as tentativas)."""


@runtime_checkable
class ExecutionProvider(Protocol):
    """Porta de execução: recebe um agente + tarefa e devolve saída estruturada."""

    id: str

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput: ...


class LocalMockExecutionProvider:
    """Provider determinístico para o MVP-1 (não executa código real).

    Gera uma `AgentOutput` com um `ContextPatch` proposto derivado da tarefa,
    permitindo exercitar todo o fluxo de governança sem LLM/CLI real.
    """

    id = "local_mock"

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        orchestration_id = str(task["orchestration_id"])
        phase = Phase(task.get("phase", Phase.F5))
        target_path = str(task["target_path"])
        content = task.get("content", f"mock::{agent.role}")
        card_id = task.get("card_id")

        patch = ContextPatch(
            orchestration_id=orchestration_id,
            card_id=card_id,
            agent=agent.role,
            phase=phase,
            patch_type=PatchType(task.get("patch_type", PatchType.UPDATE)),
            target_path=target_path,
            content=content,
            evidence=[f"Gerado por {self.id} (mock)"],
        )
        return AgentOutput(
            agent_role=agent.role,
            executor_id=self.id,
            summary=f"[mock] {agent.role} propôs alteração em '{target_path}'.",
            patches=[patch],
        )


class AgentExecutor:
    """Executa agentes através de um ExecutionProvider e registra a execução."""

    def __init__(
        self, provider: ExecutionProvider | None = None, event_log: EventLog | None = None
    ) -> None:
        self.provider: ExecutionProvider = provider or LocalMockExecutionProvider()
        self.event_log = event_log or EventLog()

    def run(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        self.event_log.append(
            "AgentRunStarted", {"agent_role": agent.role, "executor": self.provider.id}
        )
        output = self.provider.execute(agent, task)
        self.event_log.append(
            "AgentRunFinished",
            {
                "agent_role": agent.role,
                "executor": self.provider.id,
                "patches": len(output.patches),
            },
        )
        return output
