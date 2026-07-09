"""PromptBuilder — monta prompts (system+user) para agentes LLM a partir do contexto.

Injeta o papel do agente, a demanda e as seções relevantes do OrchestratorContext,
e exige resposta em JSON (para ser validada e virar um ContextPatch). Tudo em pt-BR.
"""

from __future__ import annotations

import json
from typing import Any

from aso.agents.models import AgentSpec

_SYSTEM_TEMPLATE = (
    "Você é o agente '{role}' de um runtime de engenharia de software autônoma.\n"
    "Responsabilidade: {caps}.\n"
    "Regras: responda SEMPRE em português do Brasil; NÃO escreva texto fora do JSON.\n"
    "Sua resposta DEVE ser um único objeto JSON válido, sem cercas de código, com a forma:\n"
    '{{"summary": "<resumo curto do que você produziu>", '
    '"content": <objeto com o conteúdo estruturado para a seção "{section}">}}\n'
    "O 'content' será gravado na seção '{section}' do contexto canônico via ContextBus."
)


class PromptBuilder:
    """Constrói mensagens de prompt para um agente a partir da tarefa e do contexto."""

    def build_messages(
        self, agent: AgentSpec, task: dict[str, Any], context: dict[str, Any] | None = None
    ) -> tuple[str, str]:
        section = str(task.get("target_path", "engineering")).split(".")[0]
        caps = ", ".join(agent.capabilities) or agent.role
        system = _SYSTEM_TEMPLATE.format(role=agent.role, caps=caps, section=section)

        request = ""
        content = task.get("content")
        if isinstance(content, dict):
            request = str(content.get("request") or content.get("by") or "")
        elif content is not None:
            request = str(content)

        parts = [
            f"Fase atual: {task.get('phase', '?')}",
            f"Demanda do produto: {request or '(não informada)'}",
        ]
        # Injeta apenas as seções de contexto relevantes (evita token explosion).
        if context:
            relevant = {k: context.get(k) for k in agent.context_sections if k in context}
            if relevant:
                parts.append(
                    "Contexto relevante (JSON):\n"
                    + json.dumps(relevant, ensure_ascii=False, default=str)[:6000]
                )
        parts.append(f"Produza o conteúdo estruturado da seção '{section}' para atender à demanda.")
        return system, "\n\n".join(parts)
