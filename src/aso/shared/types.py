"""Enumerações canônicas do domínio (fases, colunas, tipos de conflito etc.)."""

from __future__ import annotations

from enum import StrEnum


class Phase(StrEnum):
    """Fases da esteira F1–F7."""

    F1 = "F1"
    F2 = "F2"
    F3 = "F3"
    F4 = "F4"
    F5 = "F5"
    F6 = "F6"
    F7 = "F7"


class PatchType(StrEnum):
    """Tipos de ContextPatch (§18)."""

    ADD = "add"
    UPDATE = "update"
    PROPOSE = "propose"
    REMOVE = "remove"


class GateStatus(StrEnum):
    """Resultado de um quality gate (§22)."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"


class PatchStatus(StrEnum):
    """Situação de um ContextPatch após passar pelo ContextBus."""

    PENDING = "pending"
    APPLIED = "applied"
    REJECTED = "rejected"
    QUEUED_CONFLICT = "queued_conflict"


class ConflictType(StrEnum):
    """Catálogo de conflitos (§20)."""

    ARCHITECTURE = "ARCHITECTURE_CONFLICT"
    CONTRACT = "CONTRACT_CONFLICT"
    SECURITY = "SECURITY_CONFLICT"
    DATA_MODEL = "DATA_MODEL_CONFLICT"
    SCOPE = "SCOPE_CONFLICT"
    SNAPSHOT_LOCK = "SNAPSHOT_LOCK_CONFLICT"
    QUALITY_GATE = "QUALITY_GATE_CONFLICT"
    TOOL_PERMISSION = "TOOL_PERMISSION_CONFLICT"
    AGENT_OUTPUT = "AGENT_OUTPUT_CONFLICT"
    KANBAN_DEPENDENCY = "KANBAN_DEPENDENCY_CONFLICT"
    PR = "PR_CONFLICT"
    CI = "CI_CONFLICT"
    REVIEW = "REVIEW_CONFLICT"


class ADRStatus(StrEnum):
    """Status de uma ADR (§21)."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


class ExecutionMode(StrEnum):
    """Modos de execução da orquestração (§12)."""

    FULL_PIPELINE = "full-pipeline"
    FEATURE_EVOLUTION = "feature-evolution"
    ARCHITECTURE_REVIEW = "architecture-review"
    CODE_EXECUTION = "code-execution"
    INCIDENT_RESPONSE = "incident-response"
    PHASE_RESUME = "phase-resume"


class ProjectStatus(StrEnum):
    """Situação de um projeto no catálogo multi-repo."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class ExecutionStrategy(StrEnum):
    """Padrões multiagente (§13)."""

    SINGLE_AGENT = "single_agent"
    SEQUENTIAL = "sequential_agents"
    PARALLEL = "parallel_agents"
    AGENTS_AS_TOOLS = "agents_as_tools"
    HANDOFF = "handoff"
    SUPERVISOR_WORKER = "supervisor_worker"
    GROUP_CHAT = "group_chat_controlled"
    EVALUATOR_OPTIMIZER = "evaluator_optimizer"
    HYBRID = "hybrid"


class RiskLevel(StrEnum):
    """Nível de risco de uma tarefa/decisão."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutorType(StrEnum):
    """Tipo de executor de um papel de agente (§26A)."""

    LLM_PROVIDER = "llm_provider"
    CLI_AGENT = "cli_agent"
    STRATEGY = "strategy"


class AssigneeType(StrEnum):
    """Tipo de responsável por um card (§16.5)."""

    HUMAN = "human"
    AGENT = "agent"
    MULTI_AGENT = "multi_agent"


class ColumnKey(StrEnum):
    """Colunas do Kanban (§16.2)."""

    BACKLOG = "Backlog"
    READY = "Ready"
    PLANNING = "Planning"
    IN_PROGRESS = "InProgress"
    WAITING_AGENT = "WaitingAgent"
    WAITING_HUMAN = "WaitingHuman"
    REVIEW = "Review"
    TESTING = "Testing"
    BLOCKED = "Blocked"
    FAILED = "Failed"
    DONE = "Done"
    ARCHIVED = "Archived"


class CardType(StrEnum):
    """Tipos de card (§16.4)."""

    EPIC = "Epic"
    FEATURE = "Feature"
    TASK = "Task"
    BUG = "Bug"
    TECH_DEBT = "TechDebt"
    ADR_TASK = "ADRTask"
    RESEARCH = "Research"
    REVIEW = "Review"
    TEST = "Test"
    DOCUMENTATION = "Documentation"
    DEPLOY = "Deploy"
    INCIDENT = "Incident"
    IMPROVEMENT = "Improvement"
