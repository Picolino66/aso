"""Modelos de domínio da governança (Pydantic v2).

Materializa as entidades §17–§24 do requisito. Todas com `id` e timestamps.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from aso.shared.ids import gen_id, now_iso
from aso.shared.types import (
    ADRStatus,
    ConflictType,
    GateStatus,
    PatchStatus,
    PatchType,
    Phase,
)


class ContextPatch(BaseModel):
    """Proposta de alteração no contexto (§18). Produzida por agentes/skills."""

    id: str = Field(default_factory=lambda: gen_id("patch"))
    orchestration_id: str
    card_id: str | None = None
    agent: str
    phase: Phase
    patch_type: PatchType
    target_path: str = Field(min_length=1, description="Caminho pontilhado no contexto")
    content: Any = None
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    requires_adr: bool = False
    requires_approval: bool = False
    linked_adrs: list[str] = Field(default_factory=list)
    status: PatchStatus = PatchStatus.PENDING
    created_at: str = Field(default_factory=now_iso)


class Conflict(BaseModel):
    """Conflito detectado pelo ContextBus/ConflictDetector (§20)."""

    id: str = Field(default_factory=lambda: gen_id("conflict"))
    orchestration_id: str
    type: ConflictType
    source_patch_ids: list[str] = Field(default_factory=list)
    description: str
    resolution: str | None = None
    status: str = "open"
    created_at: str = Field(default_factory=now_iso)


class GateCriterionResult(BaseModel):
    """Resultado de um critério individual de um quality gate."""

    name: str
    status: GateStatus
    evidence: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    # Duração real da validação (Tela 16, wf §18.2, ADR-0048) — `None` para
    # critérios anteriores a esta ADR ou que não passam por comando externo
    # (predicados em memória, tempo desprezível e não medido).
    duration_ms: float | None = None


class QualityGateResult(BaseModel):
    """Resultado de um quality gate (§22)."""

    id: str = Field(default_factory=lambda: gen_id("gate"))
    orchestration_id: str
    phase: Phase
    status: GateStatus
    criteria: list[GateCriterionResult] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    approved_by: str | None = None
    created_at: str = Field(default_factory=now_iso)


class Snapshot(BaseModel):
    """Versão congelada do contexto após uma fase aprovada (§23)."""

    id: str = Field(default_factory=lambda: gen_id("snapshot"))
    orchestration_id: str
    snapshot_version: str
    phase: Phase
    context_hash: str
    frozen_sections: list[str] = Field(default_factory=list)
    quality_gate_result_id: str | None = None
    adrs: list[str] = Field(default_factory=list)
    cards: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class HumanApproval(BaseModel):
    """Solicitação de aprovação humana para ação crítica (§24)."""

    id: str = Field(default_factory=lambda: gen_id("approval"))
    orchestration_id: str
    card_id: str | None = None
    requested_by_agent: str = "OrchestratorAgent"
    action: str
    # Origem real da solicitação (dashboard §3.3, ADR-0037) — não os 4 rótulos
    # fictícios do wireframe (Discovery/Arquitetura/Deploy/Aceite final, que não
    # existem no runtime): os 3 pontos de código que criam aprovação automática
    # ("estrategia", "patch", "fase_gate"), ou "manual" quando criada via API
    # (POST .../approvals) sem vir de nenhum desses três.
    tipo: str = "manual"
    risk: str = "medium"
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    status: str = "pending"
    approved_by: str | None = None
    created_at: str = Field(default_factory=now_iso)


class PullRequest(BaseModel):
    """Pull Request derivado do worktree de um card (§26, MVP-4)."""

    id: str = Field(default_factory=lambda: gen_id("pr"))
    orchestration_id: str
    card_id: str | None = None
    branch: str
    base_branch: str = "main"
    title: str = ""
    status: str = "open"  # open | merged | closed
    ci_status: str = "pending"  # pending | passed | failed
    review_status: str = "pending"  # pending | approved | changes_requested
    # Veredito da revisão independente (ADR-0017), serializado como dict (mesmo
    # padrão de demand_brief): vazio = ainda não revisada. `reviewed_by` é o
    # executor que revisou; `review_rounds` conta quantas vezes o ciclo rodou.
    review_verdict: dict[str, Any] = Field(default_factory=dict)
    reviewed_by: str = ""
    review_rounds: int = 0
    created_at: str = Field(default_factory=now_iso)
    merged_at: str | None = None


class ReviewComment(BaseModel):
    """Comentário do revisor ancorado em arquivo/linha (wf §20.3) — ADR-0033.

    Complementa (não substitui) o parecer agregado — `ReviewVerdict`/
    `PullRequest.review_verdict` seguem existindo do mesmo jeito, populados a cada
    rodada. A ADR-0017 rejeitou tabela filha para o veredito por ele ser "mapa
    pequeno, sempre lido junto da PR"; `ReviewComment` é o caso oposto: uma lista de
    tamanho variável em que CADA item tem ciclo de vida próprio de resolução
    (pendente → resolvido), o que uma coluna JSONB no `pull_requests` não modela bem.
    """

    id: str = Field(default_factory=lambda: gen_id("comment"))
    orchestration_id: str
    pr_id: str
    card_id: str | None = None
    arquivo: str
    linha: int = 0
    categoria: str = "correcao"
    # baixa | media | alta | critica — mesmo vocabulário de QaCheck.gravidade/
    # Incident.gravidade. Distinto de `obrigatorio`: severidade é gravidade, não
    # "bloqueia ou não" (o wireframe pede os dois como campos separados, §20.3).
    severidade: str = "media"
    descricao: str
    sugestao: str = ""
    obrigatorio: bool = True
    # pendente | resolvido
    status: str = "pendente"
    # Rodada de revisão (pr.review_rounds) em que o comentário nasceu — permite
    # distinguir comentários da rodada corrente dos de rodadas já superadas.
    review_round: int = 1
    resolved_by: str = ""
    resolved_at: str | None = None
    created_at: str = Field(default_factory=now_iso)


class CandidateRun(BaseModel):
    """Resultado rastreável de uma corrida de candidatos CLI por card (§26A.6).

    Registra os candidatos avaliados (executor, branch, diff, arquivos, erro) e o
    branch recomendado pela heurística, formando um histórico auditável de corridas.
    """

    id: str = Field(default_factory=lambda: gen_id("race"))
    orchestration_id: str
    card_id: str
    recommended_branch: str | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class IncidentTimelineEntry(BaseModel):
    """Um evento da timeline de um incidente (§21, wf §27) — `Incident` é a primeira
    entidade do projeto com timeline embutida em vez de "várias instâncias formam o
    histórico" (padrão de `PullRequest`/`CandidateRun`): faz sentido aqui porque um
    incidente é UM objeto de vida longa que muda de estado, não um evento imutável."""

    evento: str  # ex.: "aberto", "investigando", "resolvido"
    detalhe: str = ""
    actor: str = "system"
    at: str = Field(default_factory=now_iso)


class Incident(BaseModel):
    """Incidente de primeira classe (§21 do fluxo.md, wf §27/§38) — ADR-0032.

    Hoje só existia `KanbanCard(type=Incident)`, criado por `rollback_deploy` —
    continua existindo (a tarefa de análise de causa raiz do §21), e `card_id`
    aponta para ele. `deploy_ambiente`/`deploy_estagio`/`deploy_versao` são um
    SNAPSHOT do `DeployRun` revertido, não uma FK real: `DeployRun` não tem `id`
    próprio (é um dict versionado no ring `deploy_runs`), então o vínculo é por
    valor, não por referência — mesma disciplina de "só registra o que o runtime
    tem à mão" já usada em `_build_card_closure`.
    """

    id: str = Field(default_factory=lambda: gen_id("incident"))
    orchestration_id: str
    card_id: str | None = None
    titulo: str
    motivo: str = ""
    # baixa | media | alta | critica — mesmo vocabulário de `QaCheck.gravidade`
    # (ADR-0025) e do exemplo do wireframe (§27.2: "Gravidade: Crítica").
    gravidade: str = "media"
    # aberto | investigando | resolvido
    status: str = "aberto"
    causa_raiz: str = ""
    deploy_ambiente: str = ""
    deploy_estagio: str = ""
    deploy_versao: int | None = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    resolved_at: str | None = None


class BugReport(BaseModel):
    """Registro estruturado de bug (Tela 21, wf §23) — ADR-0049.

    Companion do `KanbanCard(type=Bug)` — mesmo papel que `Incident` tem para
    `KanbanCard(type=Incident)` (§21): o card já existia (criado
    automaticamente por `_criar_bug_de_qa` desde a ADR-0025, ou manualmente
    aqui) e continua sendo o objeto rastreável no Kanban; `BugReport` só
    guarda os campos estruturados do wf §23.1 que nem `KanbanCard` nem
    `QaCheck` têm (impacto, frequência, agente sugerido, retorno de fluxo).
    """

    id: str = Field(default_factory=lambda: gen_id("bug"))
    orchestration_id: str
    # Card do §23.1 ("Card original") — o que tinha o problema, NÃO o bug em si.
    card_original_id: str
    # Card `type=Bug` criado para este relato — o objeto rastreável no Kanban,
    # mesmo papel que `Incident.card_id` tem para `KanbanCard(type=Incident)`.
    card_id: str
    titulo: str
    cenario: str = ""
    passos_para_reproduzir: list[str] = Field(default_factory=list)
    ambiente: str = ""
    resultado_atual: str = ""
    resultado_esperado: str = ""
    evidencias: list[str] = Field(default_factory=list)
    # baixa | media | alta | critica — mesmo vocabulário de QaCheck.gravidade/
    # Incident.gravidade.
    gravidade: str = "media"
    impacto: str = ""
    frequencia: str = ""
    agente_sugerido: str = ""
    # retornar_implementacao | retornar_infraestrutura | retornar_banco_de_dados |
    # retornar_documentacao | retornar_arquitetura | card_independente (wf §23.2).
    # Descritivo (documenta a intenção do operador), não roteamento automático
    # entre times — o runtime não tem esse mecanismo. Única exceção real:
    # "card_independente" de fato cria o bug SEM vínculo de dependência com o
    # card original (ver `create_bug_report`).
    retorno_de_fluxo: str = "retornar_implementacao"
    reportado_por: str = "system"
    created_at: str = Field(default_factory=now_iso)


class SloEvaluation(BaseModel):
    """Amostra pontual da avaliação de SLO (F7) — série temporal de burn-rate.

    Persistida a cada avaliação para permitir burn-rate/tendência sobre uma janela
    real de tempo (em vez de um cálculo instantâneo), e alimentar alertas externos.
    """

    id: str = Field(default_factory=lambda: gen_id("slo"))
    orchestration_id: str
    fail_rate: float = 0.0
    burn_rate: float = 0.0
    consumed_pct: float = 0.0
    severity: str = "ok"
    breaches: list[str] = Field(default_factory=list)
    alerts_count: int = 0
    created_at: str = Field(default_factory=now_iso)


class ADR(BaseModel):
    """Architecture Decision Record (§21)."""

    id: str
    orchestration_id: str
    title: str
    status: ADRStatus = ADRStatus.PROPOSED
    context: str = ""
    options_considered: list[dict[str, Any]] = Field(default_factory=list)
    decision: str = ""
    rationale: str = ""
    tradeoffs: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    phase: Phase
    created_by_agent: str | None = None
    reviewed_by_agent: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    linked_cards: list[str] = Field(default_factory=list)
    linked_requirements: list[str] = Field(default_factory=list)
    locked_paths: list[str] = Field(
        default_factory=list,
        description="Caminhos do contexto governados por esta ADR (override exige referenciá-la)",
    )
    timestamp: str = Field(default_factory=now_iso)
