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


class AgentDefinitionError(ValueError):
    """Definição de agente inválida (Tela 30, wf §32, ADR-0053)."""


class AgentDefinition(BaseModel):
    """Definição PERSISTENTE e editável de um agente (Tela 30, wf §32, ADR-0053).

    Diferente de `RoutingRule` (§33, ADR-0028 — configuração declarativa que só
    influencia uma decisão), este catálogo é a FONTE DE VERDADE das permissões
    reais: `ferramentas`/`permissoes` alimentam `AgentSpec.allowed_tools`/
    `context_sections` de `role` via `AgentRegistry.seed_from_catalog`, que por
    sua vez alimenta `PermissionPolicy` (deny-by-default do ContextBus, regra
    inviolável do CLAUDE.md). Editar esta definição muda de verdade o que o
    agente pode escrever — decisão confirmada com o operador, ADR-0053.

    `role` aponta para uma chave real de `AgentRegistry` (ex.
    "BackendDevelopmentAgent") quando existe um papel técnico correspondente;
    vazio para os agentes-exemplo do wireframe sem papel real ainda (nunca
    inventamos um `role` novo no registry só para preencher isso — ver
    ADR-0053 para quais dos 14 exemplos ficam sem vínculo).
    """

    id: str = Field(default_factory=lambda: gen_id("agentdef"))
    nome: str
    tipo: str = ""
    funcao: str = ""
    plataforma: str = ""
    role: str = ""
    modelos_permitidos: list[str] = Field(default_factory=list)
    efforts_permitidos: list[str] = Field(default_factory=list)
    # -> AgentSpec.allowed_tools / context_sections do `role` (quando vinculado).
    ferramentas: list[str] = Field(default_factory=list)
    permissoes: list[str] = Field(default_factory=list)
    # Vazio = sem restrição de projeto (todos) — nunca um "todos" fabricado.
    projetos: list[str] = Field(default_factory=list)
    # Vocabulário de `DemandBrief.dominios`/`decision_engine._DOMAIN_AGENT` —
    # nunca um vocabulário próprio novo (mesmo cuidado de `triage.py`).
    categorias_tarefa: list[str] = Field(default_factory=list)
    limite_custo_usd: float | None = None
    limite_tentativas: int | None = None
    exige_supervisao: bool = False
    ativo: bool = True
    created_by: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


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
