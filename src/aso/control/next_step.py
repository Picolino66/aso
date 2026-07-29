"""Motor de *próximo passo* da esteira (§14 · ADR-0013).

Traduz o estado governado de uma orquestração na única pergunta que o operador faz
ao abrir a tela de detalhe: **o que falta para seguir em frente?**

As regras que travam a esteira já existem, espalhadas pelo runtime — `start_autopilot`
exige comando de validação, `run_phase` só chega ao gate com os cards de F5/F6
entregues, `merge_pr` exige CI + review, gate reprovado bloqueia o avanço e o autopilot
pausa na aprovação humana. Reuni-las aqui, numa função **pura** sobre um retrato do
estado, mantém **uma única fonte de verdade** de governança: a UI não reimplementa as
regras, ela renderiza o que o runtime disser (mesmo princípio do ContextBus como único
escritor do contexto).

Nada aqui faz I/O: quem coleta o estado é o `OrchestrationService.next_step`, o que
deixa cada bloqueio testável isoladamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from aso.control.models import Orchestration
from aso.execution.docs_drift import DocsDriftReport
from aso.governance.models import Conflict, HumanApproval, PullRequest, QualityGateResult
from aso.kanban.models import KanbanCard
from aso.shared.types import ColumnKey, ExecutionMode, GateStatus, Phase

# Severidades, da mais urgente para a menos: definem a ordem dos bloqueios e,
# por consequência, qual deles vira a ação primária da tela.
SEVERITY_BLOCKS = "bloqueia"  # impede qualquer avanço até ser resolvido
SEVERITY_HUMAN = "aguardando_humano"  # depende de decisão governada (papel admin)
SEVERITY_OPERATOR = "acao_do_operador"  # depende de um clique seu
SEVERITY_INFO = "informativo"  # não trava a esteira

_SEVERITY_RANK = {
    SEVERITY_BLOCKS: 0,
    SEVERITY_HUMAN: 1,
    SEVERITY_OPERATOR: 2,
    SEVERITY_INFO: 3,
}

# Nomes das fases (mesma nomenclatura de docs/phases/) — a UI monta a esteira com isto.
PHASE_LABELS: dict[Phase, str] = {
    Phase.F1: "Discovery & Strategy",
    Phase.F2: "Architecture & Design",
    Phase.F3: "Data & API Contracts",
    Phase.F4: "UX/UI & Planning",
    Phase.F5: "Engineering Execution",
    Phase.F6: "Quality, Docs & Deploy",
    Phase.F7: "Operate & Evolve",
}

# Estados de um item do checklist.
STATE_OK = "ok"
STATE_CURRENT = "atual"  # "você está aqui"
STATE_PENDING = "pendente"
STATE_FAILED = "falha"


class NextStepAction(BaseModel):
    """Ação que destrava um bloqueio — já resolvida em rota da API v1."""

    label: str
    method: str = "POST"
    path: str
    role: str | None = None  # papel exigido (ex.: "admin"); None = qualquer usuário
    body: dict[str, Any] = Field(default_factory=dict)


class NextStepBlocker(BaseModel):
    """Um motivo concreto pelo qual a esteira não anda agora."""

    code: str
    severity: str
    title: str
    detail: str = ""
    action: NextStepAction | None = None


class NextStepChecklistItem(BaseModel):
    """Etapa do ciclo da fase, com o estado em que ela se encontra."""

    code: str
    state: str
    label: str


class NextStepReport(BaseModel):
    """Retrato acionável: onde estou, o que falta e qual é o próximo clique."""

    orchestration_id: str
    phase: Phase
    phase_label: str
    next_phase: Phase | None
    status: str
    headline: str
    explanation: str = ""
    cards_done: int = 0
    cards_total: int = 0
    checklist: list[NextStepChecklistItem] = Field(default_factory=list)
    blockers: list[NextStepBlocker] = Field(default_factory=list)
    primary_action: NextStepAction | None = None


@dataclass
class NextStepInput:
    """Retrato do estado da orquestração (coletado pelo serviço, sem I/O aqui)."""

    orchestration: Orchestration
    cards: list[KanbanCard] = field(default_factory=list)
    approvals: list[HumanApproval] = field(default_factory=list)
    pulls: list[PullRequest] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    gate_results: list[QualityGateResult] = field(default_factory=list)
    drift: DocsDriftReport | None = None
    # None = catálogo não configurado/indeterminado; False = executor indisponível.
    executor_available: bool | None = None
    executor_reason: str = ""
    slo_breaches: list[str] = field(default_factory=list)


def next_phase_of(phase: Phase) -> Phase | None:
    """Próxima fase da esteira F1→F7 (None em F7)."""
    order = list(Phase)
    index = order.index(phase)
    return order[index + 1] if index + 1 < len(order) else None


def _orch_path(orchestration_id: str, suffix: str) -> str:
    return f"/v1/orchestrations/{orchestration_id}{suffix}"


def _last_gate(inp: NextStepInput, phase: Phase) -> QualityGateResult | None:
    """Último resultado de gate da fase (a lista é append-only, cronológica)."""
    for gate in reversed(inp.gate_results):
        if gate.phase == phase:
            return gate
    return None


def _phase_approval(inp: NextStepInput, phase: Phase) -> HumanApproval | None:
    """Aprovação de avanço da fase (aberta por `run_phase` quando o gate passa)."""
    for approval in reversed(inp.approvals):
        payload = approval.payload or {}
        if payload.get("kind") == "phase_gate" and payload.get("phase") == phase.value:
            return approval
    return None


def _requires_delivery(inp: NextStepInput, phase: Phase) -> bool:
    """Nas fases de código com validação configurada, o gate exige cards mesclados."""
    return bool(inp.orchestration.validation_command) and phase in (Phase.F5, Phase.F6)


# ------------------------------------------------------------------ bloqueios


def _setup_blockers(inp: NextStepInput) -> list[NextStepBlocker]:
    """Pré-condições de configuração: sem elas nenhum agente roda."""
    orch = inp.orchestration
    found: list[NextStepBlocker] = []
    if not orch.target_path:
        found.append(
            NextStepBlocker(
                code="workspace_ausente",
                severity=SEVERITY_BLOCKS,
                title="Sem pasta de trabalho",
                detail=(
                    "Os agentes precisam de um workspace isolado para criar código. "
                    "Crie a orquestração a partir de um projeto com pasta definida."
                ),
            )
        )
    if orch.execution_mode == ExecutionMode.CODE_EXECUTION and not orch.validation_command:
        found.append(
            NextStepBlocker(
                code="validacao_ausente",
                severity=SEVERITY_BLOCKS,
                title="Comando de validação não configurado",
                detail=(
                    "Em execução direta, o runtime só aprova o que passa numa validação "
                    "finita (ex.: npm run build). Sem ela, o Autopilot recusa rodar."
                ),
                action=NextStepAction(
                    label="Configurar validação",
                    method="PATCH",
                    path=_orch_path(orch.id, "/execution-settings"),
                ),
            )
        )
    if inp.executor_available is False:
        found.append(
            NextStepBlocker(
                code="executor_indisponivel",
                severity=SEVERITY_BLOCKS,
                title=f"Agente '{orch.selected_executor or 'default'}' indisponível",
                detail=inp.executor_reason or "Sincronize o catálogo ou escolha outro agente.",
                action=NextStepAction(
                    label="Sincronizar catálogo de agentes",
                    path="/v1/executors/sync",
                    role="admin",
                ),
            )
        )
    if orch.target_path and not orch.workspace_prepared:
        found.append(
            NextStepBlocker(
                code="docs_first_pendente",
                severity=SEVERITY_OPERATOR,
                title="Documentação docs-first ainda não gerada",
                detail=(
                    "A doc em /docs é a fonte de verdade que os agentes leem antes do "
                    "código. O Autopilot a gera sozinho, mas você pode gerá-la agora."
                ),
                action=NextStepAction(
                    label="Gerar docs-first",
                    path=_orch_path(orch.id, "/analyze-folder"),
                ),
            )
        )
    return found


def _governance_blockers(inp: NextStepInput) -> list[NextStepBlocker]:
    """Pendências governadas que pausam o autopilot: aprovações, PRs e conflitos."""
    orch = inp.orchestration
    found: list[NextStepBlocker] = []
    for approval in inp.approvals:
        if approval.status != "pending":
            continue
        found.append(
            NextStepBlocker(
                code="aprovacao_pendente",
                severity=SEVERITY_HUMAN,
                title=approval.action,
                detail=approval.reason or "Ação crítica: exige decisão humana (papel admin).",
                action=NextStepAction(
                    label="Aprovar",
                    path=f"/v1/approvals/{approval.id}/approve",
                    role="admin",
                ),
            )
        )
    for pr in inp.pulls:
        if pr.status != "open":
            continue
        found.append(_pr_blocker(orch.id, pr))
    abertos = [c for c in inp.conflicts if c.status == "open"]
    if abertos:
        found.append(
            NextStepBlocker(
                code="conflitos_abertos",
                severity=SEVERITY_OPERATOR,
                title=f"{len(abertos)} conflito(s) de contexto em aberto",
                detail=abertos[0].description,
                action=NextStepAction(
                    label="Resolver conflito",
                    path=_orch_path(orch.id, f"/conflicts/{abertos[0].id}/resolve"),
                ),
            )
        )
    return found


def _pr_blocker(orchestration_id: str, pr: PullRequest) -> NextStepBlocker:
    """Traduz o estágio de uma PR aberta na próxima ação do merge governado (§26A.6)."""
    if pr.ci_status != "passed":
        pendente = pr.ci_status == "pending"
        return NextStepBlocker(
            code="pr_ci_pendente",
            severity=SEVERITY_OPERATOR if pendente else SEVERITY_BLOCKS,
            title=f"PR {pr.branch}: CI {'não executada' if pendente else 'reprovada'}",
            detail="O merge governado exige CI 'passed' — rode a validação na branch.",
            action=NextStepAction(
                label="Rodar CI",
                path=_orch_path(orchestration_id, f"/pulls/{pr.id}/ci/run"),
            ),
        )
    if pr.review_status != "approved":
        return NextStepBlocker(
            code="pr_review_pendente",
            severity=SEVERITY_HUMAN,
            title=f"PR {pr.branch}: revisão pendente",
            detail="CI verde. Falta a revisão para liberar o merge governado.",
            action=NextStepAction(
                label="Aprovar revisão",
                path=_orch_path(orchestration_id, f"/pulls/{pr.id}/review"),
                body={"status": "approved"},
            ),
        )
    return NextStepBlocker(
        code="pr_pronto_merge",
        severity=SEVERITY_HUMAN,
        title=f"PR {pr.branch}: pronta para merge",
        detail="CI ✓ e revisão ✓ — o merge é ação crítica e exige papel admin.",
        action=NextStepAction(
            label="Fazer merge",
            path=_orch_path(orchestration_id, f"/pulls/{pr.id}/merge"),
            role="admin",
        ),
    )


def _card_blockers(inp: NextStepInput, phase: Phase) -> list[NextStepBlocker]:
    """O trabalho da fase corrente: o que impede os cards de chegarem a Done."""
    orch = inp.orchestration
    do_ciclo = [c for c in inp.cards if c.phase == phase]
    por_status: dict[ColumnKey, list[KanbanCard]] = {}
    for card in do_ciclo:
        por_status.setdefault(card.status, []).append(card)
    # Gate já aprovado nesta fase: o trabalho acabou — quem fala é a aprovação/avanço.
    gate = _last_gate(inp, phase)
    gate_aprovado = gate is not None and gate.status == GateStatus.PASSED
    found: list[NextStepBlocker] = []
    bloqueados = por_status.get(ColumnKey.BLOCKED, [])
    if bloqueados:
        found.append(
            NextStepBlocker(
                code="cards_bloqueados",
                severity=SEVERITY_BLOCKS,
                title=f"{len(bloqueados)} card(s) bloqueado(s)",
                detail=bloqueados[0].block_reason or "Sem motivo registrado.",
                action=NextStepAction(
                    label="Desbloquear card",
                    path=_orch_path(orch.id, f"/cards/{bloqueados[0].id}/unblock"),
                ),
            )
        )
    falhos = por_status.get(ColumnKey.FAILED, [])
    if falhos:
        found.append(
            NextStepBlocker(
                code="cards_falhos",
                severity=SEVERITY_BLOCKS,
                title=f"{len(falhos)} card(s) falharam na execução",
                detail=falhos[0].block_reason or "Veja a atividade para o erro do agente.",
                action=NextStepAction(
                    label="Recolocar em execução",
                    path=_orch_path(orch.id, "/retry"),
                ),
            )
        )
    esperando = por_status.get(ColumnKey.WAITING_HUMAN, [])
    if esperando:
        found.append(
            NextStepBlocker(
                code="cards_aguardando_humano",
                severity=SEVERITY_HUMAN,
                title=f"{len(esperando)} card(s) aguardando decisão humana",
                detail="O agente produziu um patch que exige aprovação antes de aplicar.",
            )
        )
    prontos = por_status.get(ColumnKey.READY, [])
    if prontos:
        found.append(
            NextStepBlocker(
                code="cards_prontos",
                severity=SEVERITY_OPERATOR,
                title=f"{len(prontos)} card(s) em Ready aguardando execução",
                detail=(
                    "Card em Ready só roda quando você (ou o Autopilot) dispara a fase — "
                    "é a fronteira entre planejar e deixar a IA escrever código."
                ),
                action=NextStepAction(
                    label=f"Executar fase {phase.value}",
                    path=_orch_path(orch.id, "/run-phase"),
                ),
            )
        )
    backlog = por_status.get(ColumnKey.BACKLOG, [])
    if backlog:
        found.append(
            NextStepBlocker(
                code="cards_em_backlog",
                severity=SEVERITY_OPERATOR,
                title=f"{len(backlog)} card(s) no Backlog",
                detail="Mover de Backlog → Ready é o que libera a IA a executá-los.",
                action=NextStepAction(
                    label="Mover para Ready",
                    path=_orch_path(orch.id, f"/cards/{backlog[0].id}/move"),
                    body={"to_column": "Ready"},
                ),
            )
        )
    if not do_ciclo and not gate_aprovado:
        found.append(
            NextStepBlocker(
                code="sem_cards_na_fase",
                severity=SEVERITY_OPERATOR,
                title=f"Nenhum card na fase {phase.value}",
                detail=(
                    "Sem trabalho na fase, o gate é vacuamente aprovado: rodar a fase "
                    "avalia o gate e abre a aprovação de avanço."
                ),
                action=NextStepAction(
                    label=f"Rodar fase {phase.value}",
                    path=_orch_path(orch.id, "/run-phase"),
                ),
            )
        )
    entregues = por_status.get(ColumnKey.DONE, [])
    em_entrega = [c for c in do_ciclo if c.status in (ColumnKey.TESTING, ColumnKey.REVIEW)]
    if _requires_delivery(inp, phase) and em_entrega and not inp.pulls:
        found.append(
            NextStepBlocker(
                code="entrega_pendente",
                severity=SEVERITY_OPERATOR,
                title=f"{len(em_entrega)} card(s) executados sem PR aberta",
                detail=(
                    "Em F5/F6 o gate só aprova com todos os cards mesclados: abra a PR do "
                    "card para levá-lo pelo merge governado (CI + revisão)."
                ),
                action=NextStepAction(
                    label="Abrir PR",
                    path=_orch_path(orch.id, f"/cards/{em_entrega[0].id}/open-pr"),
                ),
            )
        )
    if do_ciclo and len(entregues) == len(do_ciclo) and not gate_aprovado:
        found.append(
            NextStepBlocker(
                code="gate_pendente",
                severity=SEVERITY_OPERATOR,
                title=f"Cards da fase {phase.value} concluídos",
                detail="Falta rodar o quality gate para congelar o snapshot da fase.",
                action=NextStepAction(
                    label=f"Rodar fase {phase.value}",
                    path=_orch_path(orch.id, "/run-phase"),
                ),
            )
        )
    return found


def _gate_blockers(inp: NextStepInput, phase: Phase) -> list[NextStepBlocker]:
    """Gate reprovado e sinais não-bloqueantes (drift de docs, SLO)."""
    orch = inp.orchestration
    found: list[NextStepBlocker] = []
    gate = _last_gate(inp, phase)
    if gate is not None and gate.status == GateStatus.FAILED:
        motivos = gate.blocking_issues or [
            c.failure_reason or c.name for c in gate.criteria if c.status == GateStatus.FAILED
        ]
        found.append(
            NextStepBlocker(
                code="gate_reprovado",
                severity=SEVERITY_BLOCKS,
                title=f"Quality gate de {phase.value} reprovado",
                detail=" · ".join(gate.required_actions or motivos) or "Sem detalhe registrado.",
                action=NextStepAction(
                    label="Rodar gate novamente",
                    path=_orch_path(orch.id, "/quality-gates/run"),
                ),
            )
        )
    if inp.drift is not None and inp.drift.has_drift:
        partes: list[str] = []
        if inp.drift.undocumented_modules:
            partes.append(f"{len(inp.drift.undocumented_modules)} módulo(s) sem doc")
        if inp.drift.orphan_module_docs:
            partes.append(f"{len(inp.drift.orphan_module_docs)} doc(s) órfã(s)")
        if inp.drift.broken_links:
            partes.append(f"{len(inp.drift.broken_links)} link(s) quebrado(s)")
        if inp.drift.unfilled_features:
            partes.append(f"{len(inp.drift.unfilled_features)} doc(s) por preencher")
        found.append(
            NextStepBlocker(
                code="drift_docs",
                severity=SEVERITY_INFO,
                title="Documentação fora de sincronia com o código",
                detail=" · ".join(partes),
                action=NextStepAction(
                    label="Sincronizar docs",
                    path=_orch_path(orch.id, "/docs-heal"),
                ),
            )
        )
    if inp.slo_breaches:
        found.append(
            NextStepBlocker(
                code="slo_em_risco",
                severity=SEVERITY_INFO,
                title="SLOs em risco",
                detail=" · ".join(inp.slo_breaches),
            )
        )
    return found


# ------------------------------------------------------------------ checklist


def _checklist(inp: NextStepInput, phase: Phase) -> list[NextStepChecklistItem]:
    """Ciclo de vida da fase, do setup à aprovação — com o ponto em que você está."""
    orch = inp.orchestration
    do_ciclo = [c for c in inp.cards if c.phase == phase]
    executados = [c for c in do_ciclo if c.status not in (ColumnKey.BACKLOG, ColumnKey.READY)]
    entregues = [c for c in do_ciclo if c.status == ColumnKey.DONE]
    gate = _last_gate(inp, phase)
    approval = _phase_approval(inp, phase)
    nxt = next_phase_of(phase)

    itens = [
        NextStepChecklistItem(
            code="workspace",
            state=STATE_OK if orch.target_path else STATE_PENDING,
            label=f"Pasta de trabalho: {orch.target_path or 'não definida'}",
        ),
        NextStepChecklistItem(
            code="docs_first",
            state=STATE_OK if orch.workspace_prepared else STATE_PENDING,
            label="Documentação docs-first gerada",
        ),
        NextStepChecklistItem(
            code="validacao",
            state=STATE_OK if orch.validation_command else STATE_PENDING,
            label=f"Comando de validação: {orch.validation_command or 'não configurado'}",
        ),
        NextStepChecklistItem(
            code="cards_executados",
            state=STATE_OK if do_ciclo and len(executados) == len(do_ciclo) else STATE_PENDING,
            label=f"Cards da fase executados ({len(executados)} de {len(do_ciclo)})",
        ),
    ]
    if _requires_delivery(inp, phase):
        itens.append(
            NextStepChecklistItem(
                code="entrega",
                state=STATE_OK if do_ciclo and len(entregues) == len(do_ciclo) else STATE_PENDING,
                label=f"Entregas mescladas com CI + revisão ({len(entregues)} de {len(do_ciclo)})",
            )
        )
    itens.append(
        NextStepChecklistItem(
            code="gate",
            state=_gate_state(gate),
            label=f"Quality gate de {phase.value}",
        )
    )
    itens.append(
        NextStepChecklistItem(
            code="aprovacao",
            state=_approval_state(approval),
            label=(
                f"Aprovação humana para avançar a {nxt.value}"
                if nxt
                else "Aprovação humana da última fase (F7)"
            ),
        )
    )
    for item in itens:  # o primeiro pendente é o "você está aqui"
        if item.state == STATE_PENDING:
            item.state = STATE_CURRENT
            break
    return itens


def _gate_state(gate: QualityGateResult | None) -> str:
    if gate is None:
        return STATE_PENDING
    if gate.status == GateStatus.FAILED:
        return STATE_FAILED
    return STATE_OK


def _approval_state(approval: HumanApproval | None) -> str:
    if approval is None:
        return STATE_PENDING
    if approval.status == "approved":
        return STATE_OK
    if approval.status == "rejected":
        return STATE_FAILED
    return STATE_PENDING


# ------------------------------------------------------------------ orquestração


def compute_next_step(inp: NextStepInput) -> NextStepReport:
    """Calcula o próximo passo da esteira a partir de um retrato do estado."""
    orch = inp.orchestration
    phase = orch.current_phase
    do_ciclo = [c for c in inp.cards if c.phase == phase]
    entregues = [c for c in do_ciclo if c.status == ColumnKey.DONE]
    report = NextStepReport(
        orchestration_id=orch.id,
        phase=phase,
        phase_label=PHASE_LABELS.get(phase, phase.value),
        next_phase=next_phase_of(phase),
        status=orch.status,
        headline="",
        cards_done=len(entregues),
        cards_total=len(do_ciclo),
        checklist=_checklist(inp, phase),
    )
    terminal = _terminal_report(inp, report)
    if terminal is not None:
        return terminal

    blockers = [
        *_setup_blockers(inp),
        *_governance_blockers(inp),
        *_card_blockers(inp, phase),
        *_gate_blockers(inp, phase),
    ]
    blockers.sort(key=lambda b: _SEVERITY_RANK.get(b.severity, 99))
    report.blockers = blockers
    acionaveis = [b for b in blockers if b.action is not None]
    if acionaveis:
        report.primary_action = acionaveis[0].action
    bloqueantes = [b for b in blockers if b.severity != SEVERITY_INFO]
    if bloqueantes:
        report.headline = bloqueantes[0].title
        report.explanation = bloqueantes[0].detail
    else:
        report.headline = f"Fase {phase.value} pronta para avançar"
        report.explanation = (
            "Nenhuma pendência bloqueante. Avance a fase para seguir a esteira."
            if report.next_phase
            else "Última fase da esteira concluída."
        )
        if report.next_phase:
            report.primary_action = NextStepAction(
                label=f"Avançar para {report.next_phase.value}",
                path=_orch_path(orch.id, "/advance-phase"),
                role="admin",
            )
    return report


def _terminal_report(inp: NextStepInput, report: NextStepReport) -> NextStepReport | None:
    """Estados que encerram a conversa: cancelada ou esteira concluída."""
    orch = inp.orchestration
    if orch.status == "cancelled":
        report.headline = "Orquestração cancelada"
        report.explanation = "O kill-switch bloqueia execuções. Retome para voltar a rodar."
        report.blockers = [
            NextStepBlocker(
                code="cancelada",
                severity=SEVERITY_BLOCKS,
                title="Orquestração cancelada",
                detail="Nenhum agente roda enquanto o kill-switch estiver ativo.",
                action=NextStepAction(label="Retomar", path=_orch_path(orch.id, "/resume")),
            )
        ]
        report.primary_action = report.blockers[0].action
        return report
    if orch.status == "completed":
        report.headline = "Esteira concluída"
        report.explanation = "Todas as fases passaram pelo gate e pela aprovação humana."
        return report
    return None
