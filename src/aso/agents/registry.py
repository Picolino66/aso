"""AgentRegistry (req §15, TASK-07).

Registra os agentes especializados, suas capacidades, permissões de tools e as
seções do contexto que podem escrever (usado para compor a PermissionPolicy do ContextBus).
"""

from __future__ import annotations

from aso.agents.models import AgentDefinition, AgentSpec
from aso.shared.types import ExecutorType, Phase

# Fase padrão de cada papel na esteira (MEL-20). Declarada em vez de adivinhada por
# substring do nome — a heurística antiga mandava `RequirementsAgent` para F4 (casava "ui"
# em "req-ui-rements"), `ProductStrategyAgent` para F5 e `DevOpsAgent` para F5.
FASE_PADRAO_POR_PAPEL: dict[str, Phase] = {
    "OrchestratorAgent": Phase.F1,
    "ProductStrategyAgent": Phase.F1,
    "RequirementsAgent": Phase.F1,
    "ArchitectureDesignAgent": Phase.F2,
    "SecurityAgent": Phase.F2,
    "DataApiContractsAgent": Phase.F3,
    "DatabaseAgent": Phase.F3,
    "UxPlanningAgent": Phase.F4,
    "BackendDevelopmentAgent": Phase.F5,
    "FrontendDevelopmentAgent": Phase.F5,
    "ConflictResolutionAgent": Phase.F5,
    "DevOpsAgent": Phase.F6,
    "TestingAgent": Phase.F6,
    "DocumentationAgent": Phase.F6,
    "ReviewAgent": Phase.F6,
    "FinalResponseAgent": Phase.F7,
}


def fase_padrao(role: str) -> Phase:
    """Fase padrão do papel; papel fora da tabela (catálogo customizado) cai em F5."""
    return FASE_PADRAO_POR_PAPEL.get(role, Phase.F5)


# Definição-base dos 16 agentes obrigatórios (req §15). Mantida enxuta no MVP-1.
_DEFAULT_AGENTS: list[dict[str, object]] = [
    {
        "role": "OrchestratorAgent",
        "reservado": True,
        "context_sections": ["orchestration"],
        "capabilities": ["coordinate"],
    },
    {
        "role": "ProductStrategyAgent",
        "reservado": True,
        "context_sections": ["product", "market", "business", "scope"],
    },
    {"role": "RequirementsAgent", "reservado": True, "context_sections": ["requirements", "scope"]},
    {"role": "ArchitectureDesignAgent", "context_sections": ["architecture"]},
    {"role": "DataApiContractsAgent", "context_sections": ["contracts"]},
    {
        "role": "UxPlanningAgent",
        "reservado": True,
        "context_sections": ["ux", "engineering", "kanban"],
    },
    {
        "role": "BackendDevelopmentAgent",
        "context_sections": ["engineering"],
        "default_executor": ExecutorType.CLI_AGENT,
    },
    {
        "role": "FrontendDevelopmentAgent",
        "context_sections": ["engineering", "ux"],
        "default_executor": ExecutorType.CLI_AGENT,
    },
    {"role": "DatabaseAgent", "context_sections": ["contracts", "engineering"]},
    {"role": "DevOpsAgent", "context_sections": ["operations"]},
    {
        "role": "TestingAgent",
        "context_sections": ["quality", "engineering"],
        "default_executor": ExecutorType.CLI_AGENT,
    },
    {"role": "SecurityAgent", "context_sections": ["architecture", "quality"]},
    {"role": "DocumentationAgent", "context_sections": ["engineering", "agentic"]},
    {"role": "ReviewAgent", "context_sections": ["quality"]},
    {"role": "ConflictResolutionAgent", "context_sections": ["conflicts", "adrs"]},
    {"role": "FinalResponseAgent", "reservado": True, "context_sections": ["metadata"]},
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
        """Registra os 16 agentes obrigatórios (req §15) com defaults do MVP-1."""
        for data in _DEFAULT_AGENTS:
            self.register(AgentSpec(**data))  # type: ignore[arg-type]

    def seed_from_catalog(self, definitions: list[AgentDefinition]) -> None:
        """Semeia os 16 papéis-base e aplica o catálogo persistente por cima
        (Tela 30, wf §32, ADR-0053) — quando existe uma `AgentDefinition` ativa
        vinculada a um `role`, ELA passa a decidir as `context_sections` daquele
        papel, substituindo o hardcoded (fonte de
        verdade das permissões, decisão confirmada com o operador). Papel sem
        definição correspondente mantém o hardcoded — nunca fica sem entrada
        (isso revogaria a permissão por omissão, o oposto do que o catálogo
        quer expressar quando simplesmente não foi customizado ainda)."""
        self.seed_defaults()
        for definicao in definitions:
            if not definicao.role or not definicao.ativo:
                continue
            base = self._agents.get(definicao.role)
            if base is None:
                continue
            self.register(base.model_copy(update={"context_sections": list(definicao.permissoes)}))

    def permission_map(self) -> dict[str, list[str]]:
        """Deriva o mapa de permissões (agente -> seções) para o ContextBus."""
        return {role: spec.context_sections for role, spec in self._agents.items()}
