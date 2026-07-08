"""Modelos do Agent Plane (§15, §26A)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from aso.governance.models import ContextPatch
from aso.shared.ids import gen_id, now_iso
from aso.shared.types import ExecutorType


class AgentSpec(BaseModel):
    """Definição de um agente especializado registrado no runtime."""

    id: str = Field(default_factory=lambda: gen_id("agent"))
    role: str
    capabilities: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    requires_approval_for: list[str] = Field(default_factory=list)
    default_executor: ExecutorType = ExecutorType.LLM_PROVIDER
    context_sections: list[str] = Field(
        default_factory=list, description="Seções do contexto que o agente pode escrever"
    )
    created_at: str = Field(default_factory=now_iso)


class AgentOutput(BaseModel):
    """Saída estruturada de uma execução de agente.

    O agente NÃO altera o contexto: ele propõe `patches` que serão submetidos ao
    ContextBus (§8.3).
    """

    id: str = Field(default_factory=lambda: gen_id("output"))
    agent_role: str
    executor_id: str
    summary: str
    patches: list[ContextPatch] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
