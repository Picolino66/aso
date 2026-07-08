"""AgentRegistry (§15, TASK-07).

Registra os agentes especializados, suas capacidades, permissões de tools e as
seções do contexto que podem escrever (usado para compor a PermissionPolicy do ContextBus).
"""

from __future__ import annotations

from aso.agents.models import AgentSpec
from aso.shared.types import ExecutorType

# Definição-base dos 16 agentes obrigatórios (§15). Mantida enxuta no MVP-1.
_DEFAULT_AGENTS: list[dict[str, object]] = [
    {
        "role": "OrchestratorAgent",
        "context_sections": ["orchestration"],
        "capabilities": ["coordinate"],
    },
    {
        "role": "ProductStrategyAgent",
        "context_sections": ["product", "market", "business", "scope"],
    },
    {"role": "RequirementsAgent", "context_sections": ["requirements", "scope"]},
    {"role": "ArchitectureDesignAgent", "context_sections": ["architecture"]},
    {"role": "DataApiContractsAgent", "context_sections": ["contracts"]},
    {"role": "UxPlanningAgent", "context_sections": ["ux", "engineering", "kanban"]},
    {
        "role": "BackendDevelopmentAgent",
        "context_sections": ["engineering"],
        "default_executor": ExecutorType.CLI_AGENT,
        "allowed_tools": ["read_file", "write_file", "run_tests", "run_lint", "run_build"],
        "requires_approval_for": ["delete_file", "database_reset", "deploy"],
    },
    {
        "role": "FrontendDevelopmentAgent",
        "context_sections": ["engineering", "ux"],
        "default_executor": ExecutorType.CLI_AGENT,
    },
    {"role": "DatabaseAgent", "context_sections": ["contracts", "engineering"]},
    {
        "role": "DevOpsAgent",
        "context_sections": ["operations"],
        "requires_approval_for": ["deploy"],
    },
    {
        "role": "TestingAgent",
        "context_sections": ["quality", "engineering"],
        "default_executor": ExecutorType.CLI_AGENT,
    },
    {
        "role": "SecurityAgent",
        "context_sections": ["architecture", "quality"],
        "requires_approval_for": ["write_file", "deploy"],
    },
    {"role": "DocumentationAgent", "context_sections": ["engineering", "agentic"]},
    {"role": "ReviewAgent", "context_sections": ["quality"]},
    {"role": "ConflictResolutionAgent", "context_sections": ["conflicts", "adrs"]},
    {"role": "FinalResponseAgent", "context_sections": ["metadata"]},
]


class AgentRegistry:
    """Registro in-memory de agentes."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentSpec] = {}

    def register(self, spec: AgentSpec) -> AgentSpec:
        self._agents[spec.role] = spec
        return spec

    def get(self, role: str) -> AgentSpec | None:
        return self._agents.get(role)

    def list_all(self) -> list[AgentSpec]:
        return sorted(self._agents.values(), key=lambda a: a.role)

    def seed_defaults(self) -> None:
        """Registra os 16 agentes obrigatórios (§15) com defaults do MVP-1."""
        for data in _DEFAULT_AGENTS:
            self.register(AgentSpec(**data))  # type: ignore[arg-type]

    def permission_map(self) -> dict[str, list[str]]:
        """Deriva o mapa de permissões (agente -> seções) para o ContextBus."""
        return {role: spec.context_sections for role, spec in self._agents.items()}
