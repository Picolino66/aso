"""LlmExecutionProvider — executa um card via LLM (M1 do autopilot).

Recebe o agente + tarefa, monta o prompt com o PromptBuilder, chama o LlmClient,
faz o parse do JSON e devolve uma AgentOutput com um ContextPatch proposto (que o
ContextBus valida/aplica). O contexto é injetado via `context_provider` (callable),
evitando acoplar o provider ao OrchestrationService.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from aso.agents.models import AgentOutput, AgentSpec
from aso.agents.prompt_builder import PromptBuilder
from aso.execution.llm_client import LlmClient, LlmError
from aso.governance.models import ContextPatch
from aso.shared.types import PatchType, Phase

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_llm_json(text: str) -> dict[str, Any]:
    """Extrai o objeto JSON da resposta do LLM (tolera cercas de código)."""
    cleaned = _FENCE.sub("", text).strip()
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: tenta o maior trecho entre a primeira '{' e a última '}'.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise LlmError(f"Resposta do LLM não é JSON: {text[:200]}") from None
        obj = json.loads(cleaned[start : end + 1])
    if not isinstance(obj, dict):
        raise LlmError("Resposta JSON do LLM não é um objeto.")
    return obj


class LlmExecutionProvider:
    """ExecutionProvider que delega a um LlmClient e devolve um ContextPatch."""

    def __init__(
        self,
        client: LlmClient,
        *,
        prompt_builder: PromptBuilder | None = None,
        context_provider: Callable[[str], dict[str, Any]] | None = None,
        executor_id: str | None = None,
    ) -> None:
        self.id = executor_id or f"llm:{client.id}"
        self._client = client
        self._prompts = prompt_builder or PromptBuilder()
        self._context_provider = context_provider

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        context = None
        oid = str(task.get("orchestration_id", ""))
        if self._context_provider and oid:
            context = self._context_provider(oid)
        system, user = self._prompts.build_messages(agent, task, context)
        raw = self._client.complete(system=system, user=user)
        parsed = parse_llm_json(raw)
        summary = str(parsed.get("summary") or f"[llm] {agent.role}")
        content = parsed.get("content", parsed)

        patch = ContextPatch(
            orchestration_id=oid,
            card_id=task.get("card_id"),
            agent=agent.role,
            phase=Phase(task.get("phase", Phase.F5)),
            patch_type=PatchType(task.get("patch_type", PatchType.UPDATE)),
            target_path=str(task["target_path"]),
            content=content,
            evidence=[f"Gerado por {self.id}"],
        )
        return AgentOutput(
            agent_role=agent.role,
            executor_id=self.id,
            summary=summary,
            patches=[patch],
            artifacts={"raw": raw[:2000]},
        )
