"""Modelos do Agent Plane (req §15, §26A)."""

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
    default_executor: ExecutorType = ExecutorType.LLM_PROVIDER
    context_sections: list[str] = Field(
        default_factory=list, description="Seções do contexto que o agente pode escrever"
    )
    # Papel sem card planejado hoje (MEL-53, ADR-0075): continua no registro — permissões e o
    # catálogo de agentes o referenciam —, mas o console o mostra como reservado.
    reservado: bool = False
    created_at: str = Field(default_factory=now_iso)


class AgentDefinitionError(ValueError):
    """Definição de agente inválida (Tela 30, wf §32, ADR-0053)."""


class AgentDefinition(BaseModel):
    """Definição PERSISTENTE e editável de um agente (Tela 30, wf §32, ADR-0053).

    Diferente de `RoutingRule` (req §33, ADR-0028 — configuração declarativa que só
    influencia uma decisão), este catálogo é a FONTE DE VERDADE das permissões
    reais: `permissoes` alimenta as `context_sections` de `role` via
    `AgentRegistry.seed_from_catalog`, que por
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
    # INFORMATIVOS (MEL-53, ADR-0075): `plataforma`, `modelos_permitidos`, `efforts_permitidos`,
    # `ferramentas`, `projetos`, `categorias_tarefa` e `exige_supervisao` são persistidos e
    # exibidos, mas nenhum caminho de execução os aplica — o console os marca assim.
    modelos_permitidos: list[str] = Field(default_factory=list)
    efforts_permitidos: list[str] = Field(default_factory=list)
    ferramentas: list[str] = Field(default_factory=list)
    # -> context_sections do `role` (quando vinculado): esta SIM é a permissão real.
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
    ContextBus (req §8.3).
    """

    id: str = Field(default_factory=lambda: gen_id("output"))
    agent_role: str
    executor_id: str
    summary: str
    patches: list[ContextPatch] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
