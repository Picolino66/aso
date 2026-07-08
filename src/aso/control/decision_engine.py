"""MultiAgentDecisionEngine (§14, TASK-06).

Decide, por regras determinísticas, se a demanda usa um único agente ou múltiplos
agentes, qual padrão de execução (§13) e se exige aprovação humana. Sempre com justificativa.
"""

from __future__ import annotations

from aso.control.models import DecisionInput, MultiAgentDecision, PlannedAgent
from aso.shared.types import ExecutionStrategy, RiskLevel

# Impactos que exigem aprovação humana (§24) ou elevam o risco (§14).
_SENSITIVE_IMPACTS = {"architecture", "contract", "security", "database", "deploy"}
_APPROVAL_IMPACTS = {"deploy", "secrets", "database_reset", "branch_main"}

# Mapa domínio -> papel de agente (§15) para compor o time.
_DOMAIN_AGENT = {
    "backend": "BackendDevelopmentAgent",
    "frontend": "FrontendDevelopmentAgent",
    "database": "DatabaseAgent",
    "architecture": "ArchitectureDesignAgent",
    "contract": "DataApiContractsAgent",
    "security": "SecurityAgent",
    "tests": "TestingAgent",
    "docs": "DocumentationAgent",
    "devops": "DevOpsAgent",
}


class MultiAgentDecisionEngine:
    """Escolhe a estratégia de execução para uma demanda (§13, §14)."""

    def decide(self, inp: DecisionInput) -> MultiAgentDecision:
        high_risk = inp.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        multi_domain = len(inp.domains) > 1
        sensitive = bool(set(inp.impacts) & _SENSITIVE_IMPACTS)

        multi_signals = [
            multi_domain,
            high_risk,
            inp.needs_independent_review,
            inp.parallelizable and multi_domain,
            sensitive,
        ]
        use_multi = any(multi_signals)

        strategy, reason = self._choose_strategy(inp, use_multi, multi_domain)
        requires_approval = inp.risk_level == RiskLevel.CRITICAL or bool(
            set(inp.impacts) & _APPROVAL_IMPACTS
        )
        agents = self._build_team(inp, strategy)

        return MultiAgentDecision(
            execution_mode=strategy,
            reason=reason,
            risk_level=inp.risk_level,
            requires_human_approval=requires_approval,
            agents=agents,
            success_criteria=[f"Demanda '{inp.user_request[:60]}' atendida e revisada"],
            fallback_strategy="Reduzir para single_agent supervisionado ou escalar para humano.",
        )

    def _choose_strategy(
        self, inp: DecisionInput, use_multi: bool, multi_domain: bool
    ) -> tuple[ExecutionStrategy, str]:
        if not use_multi:
            return (
                ExecutionStrategy.SINGLE_AGENT,
                "Tarefa de baixo risco, domínio único e sem necessidade de revisão independente.",
            )
        if inp.parallelizable and multi_domain:
            return (
                ExecutionStrategy.PARALLEL,
                "Domínios independentes e paralelizáveis: execução paralela.",
            )
        if inp.needs_independent_review:
            return (
                ExecutionStrategy.EVALUATOR_OPTIMIZER,
                "Requer geração e revisão independente iterativa.",
            )
        if multi_domain:
            return (
                ExecutionStrategy.SEQUENTIAL,
                "Múltiplos domínios com dependência entre etapas: execução sequencial.",
            )
        if inp.risk_level == RiskLevel.CRITICAL:
            return (
                ExecutionStrategy.SUPERVISOR_WORKER,
                "Demanda crítica: supervisor decompõe e distribui o trabalho.",
            )
        return (
            ExecutionStrategy.SEQUENTIAL,
            "Risco/impacto relevante: execução coordenada com revisão.",
        )

    def _build_team(self, inp: DecisionInput, strategy: ExecutionStrategy) -> list[PlannedAgent]:
        if strategy == ExecutionStrategy.SINGLE_AGENT:
            role = _DOMAIN_AGENT.get(
                inp.domains[0] if inp.domains else "backend", "BackendDevelopmentAgent"
            )
            return [
                PlannedAgent(agent=role, role="primary", reason="Único domínio de baixo risco.")
            ]

        parallel = strategy == ExecutionStrategy.PARALLEL
        agents: list[PlannedAgent] = []
        for domain in inp.domains:
            role = _DOMAIN_AGENT.get(domain, "BackendDevelopmentAgent")
            agents.append(
                PlannedAgent(
                    agent=role,
                    role="worker",
                    reason=f"Responsável pelo domínio '{domain}'.",
                    parallel_group="pg1" if parallel else None,
                )
            )
        # Revisão independente sempre presente em execução multiagente.
        agents.append(
            PlannedAgent(
                agent="ReviewAgent",
                role="reviewer",
                reason="Revisão independente de qualidade, arquitetura e contratos.",
                depends_on=[a.agent for a in agents],
            )
        )
        return agents
