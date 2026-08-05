"""Modelos do Control Plane (§14)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from aso.shared.ids import gen_id, now_iso
from aso.shared.types import ExecutionMode, ExecutionStrategy, Phase, ProjectStatus, RiskLevel


class Project(BaseModel):
    """Projeto do catálogo multi-repo; agrupa orquestrações sem possuí-las."""

    id: str = Field(default_factory=lambda: gen_id("proj"))
    name: str
    description: str = ""
    target_path: str | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    archived_at: str | None = None


class ProjectEvent(BaseModel):
    """Evento append-only para auditar o ciclo de vida de um projeto."""

    id: str = Field(default_factory=lambda: gen_id("projevt"))
    project_id: str
    type: str
    actor: str
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


# Chave reservada em `Orchestration.agent_assignments` para o agente que gera nomes de
# branch e mensagens de commit. Não é uma fase da esteira: pode ser trocada a qualquer
# momento, inclusive com a orquestração já em andamento.
NAMING_KEY = "naming"

# Chave reservada para o agente de triagem da demanda (§1/§2 do fluxo.md). Mesmo
# regime do NAMING_KEY: não é fase da esteira, sempre editável.
TRIAGE_KEY = "triagem"

# Chave reservada para o agente de revisão independente de código (§14, ADR-0017).
# Mesmo regime do NAMING_KEY: não é fase da esteira, sempre editável.
REVIEW_KEY = "revisao"

# Chave reservada para o agente de discovery (§3, ADR-0020). Mesmo regime do
# NAMING_KEY: não é fase da esteira, sempre editável.
DISCOVERY_KEY = "discovery"

# Chave reservada para o agente de especificação (§5, ADR-0021). Mesmo regime do
# NAMING_KEY: não é fase da esteira, sempre editável.
SPEC_KEY = "especificacao"


# Categorias válidas de uma verificação da bateria (§12 do fluxo.md) — vocabulário
# fechado para o diagnóstico de falha (ADR-0019/ADR-0022) poder mapear categoria ->
# causa sem depender de heurística por palavra-chave.
CATEGORIAS_VALIDACAO = frozenset(
    {
        "formatacao",
        "lint",
        "compilacao",
        "tipos",
        "testes",
        "integracao",
        "contrato",
        "e2e",
        "estatica",
        "dependencias",
        "seguranca",
        "migrations",
        "documentacao",
        "cobertura",
        "desempenho",
    }
)


class ValidationCheck(BaseModel):
    """Uma verificação nomeada da bateria do §12 (ADR-0022) — não mais um único
    comando indiferenciado: o gate sabe QUAL verificação falhou, não só que "o
    comando falhou"."""

    nome: str
    comando: str
    categoria: str = "testes"
    bloqueante: bool = True


class AgentAssignment(BaseModel):
    """Executor escolhido para uma etapa específica da esteira (ADR-0014).

    Existe porque as fases têm custos e exigências diferentes: um modelo barato basta
    para F1 (discovery), enquanto F5 (código) costuma pedir o mais forte disponível.
    """

    executor: str
    effort: str | None = None


class Orchestration(BaseModel):
    """Instância de uma orquestração (§17)."""

    id: str = Field(default_factory=lambda: gen_id("orch"))
    project_id: str | None = None
    # Pasta de trabalho desta orquestração (workspace): onde os agentes CLI criam
    # código e rodam gates, substituindo o `ASO_TARGET_REPO` global só para ela.
    # `None` → cai no comportamento legado (env/provider global).
    target_path: str | None = None
    # Configuração efetiva da execução, preservada para a UI não exibir um default falso.
    # `selected_*` é o padrão da orquestração; `agent_assignments` sobrescreve por etapa.
    selected_executor: str | None = None
    selected_effort: str | None = None
    # Chaves: "F1".."F7" (etapas da esteira) e NAMING_KEY ("naming", o agente que batiza
    # branches e commits). Etapa sem entrada aqui herda `selected_*`.
    agent_assignments: dict[str, AgentAssignment] = Field(default_factory=dict)
    # Ficha estruturada da demanda (§1/§2 do fluxo.md), produzida na criação pelo agente
    # de triagem ou pela heurística. É o que alimenta o DecisionInput — sem ela o motor
    # de decisão roda sobre uma constante. Guardada como dict (não como DemandBrief) para
    # espelhar agent_assignments e manter a serialização do repositório simples.
    demand_brief: dict[str, Any] = Field(default_factory=dict)
    # Ring de até 5 versões do relatório de discovery (§3/§4, ADR-0020, versionado
    # pela ADR-0021 §4.2) — a última é a versão corrente. Lista vazia = discovery
    # nunca rodado — não regride o gate de F1 de nenhuma orquestração que não passar
    # por `POST .../discovery/run`.
    discovery_reports: list[dict[str, Any]] = Field(default_factory=list)
    # Ring de até 5 versões da especificação da solução (§5/§6, ADR-0021) — mesmo
    # raciocínio de `discovery_reports`. Lista vazia = especificação nunca gerada.
    spec_documents: list[dict[str, Any]] = Field(default_factory=list)
    validation_command: str | None = None
    # Bateria nomeada do §12 (ADR-0022). Vazia = a orquestração ainda usa só o
    # `validation_command` legado — `checks_efetivos` (control/validation.py)
    # resolve os dois num único formato, sem mudar comportamento de nenhuma
    # orquestração existente.
    validation_checks: list[ValidationCheck] = Field(default_factory=list)
    # Implantação governada (§18-22, ADR-0023): comando configurável pelo
    # operador — o runtime não provisiona infraestrutura, só orquestra o
    # comando (mesma disciplina de `validation_command`/`validation_checks`).
    deploy_command: str | None = None
    deploy_environment: str = "producao"
    # Verificações pós-implantação (§20) — reaproveita ValidationCheck: um
    # health check é "nome + comando + categoria + bloqueante", igual a uma
    # verificação da bateria.
    deploy_health_checks: list[ValidationCheck] = Field(default_factory=list)
    deploy_rollback_command: str | None = None
    # Ring de até 5 tentativas de implantação (control/documentos.py) — mesmo
    # raciocínio de discovery_reports/spec_documents. Lista vazia = nunca
    # implantou — não regride o gate de F6 de nenhuma orquestração existente.
    deploy_runs: list[dict[str, Any]] = Field(default_factory=list)
    # Orçamento com freio (§1.2/§3.2 do plano7.md, ADR-0026): `None` = sem teto,
    # comportamento idêntico a toda orquestração anterior a este incremento — o
    # teto é opt-in. `ASO_ORCAMENTO_PADRAO_USD` preenche o default de orquestrações
    # novas em `create_orchestration`, não aqui (Pydantic não lê env em default).
    orcamento_usd: float | None = None
    workspace_prepared: bool = False
    execution_mode: ExecutionMode = ExecutionMode.FULL_PIPELINE
    # A esteira começa em F1 (discovery) e avança até F7 sob o autopilot.
    current_phase: Phase = Phase.F1
    snapshot_version: str = "O0"
    status: str = "created"
    user_request: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class DecisionInput(BaseModel):
    """Entrada do MultiAgentDecisionEngine (§14)."""

    user_request: str
    current_phase: Phase = Phase.F4
    risk_level: RiskLevel = RiskLevel.LOW
    domains: list[str] = Field(default_factory=list)
    parallelizable: bool = False
    needs_independent_review: bool = False
    impacts: list[str] = Field(
        default_factory=list, description="Ex.: architecture, contract, security, database, deploy"
    )


class PlannedAgent(BaseModel):
    agent: str
    role: str = "primary"
    reason: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    parallel_group: str | None = None


class MultiAgentDecision(BaseModel):
    """Saída do MultiAgentDecisionEngine (§14)."""

    execution_mode: ExecutionStrategy
    reason: str
    risk_level: RiskLevel
    requires_human_approval: bool = False
    agents: list[PlannedAgent] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    fallback_strategy: str = ""


class ExecutionPlan(BaseModel):
    """Plano de execução de uma orquestração (§14, domain-model)."""

    id: str = Field(default_factory=lambda: gen_id("plan"))
    orchestration_id: str
    execution_mode: ExecutionMode
    strategy: ExecutionStrategy
    reason: str
    risk_level: RiskLevel
    requires_human_approval: bool = False
    agents: list[PlannedAgent] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    fallback_strategy: str = ""
    created_at: str = Field(default_factory=now_iso)
