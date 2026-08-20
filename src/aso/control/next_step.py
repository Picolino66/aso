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
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from aso.control.deploy import (
    ACEITE_AGUARDANDO_HUMANO as DEPLOY_ACEITE_AGUARDANDO_HUMANO,
)
from aso.control.deploy import (
    ACEITE_APROVADO as DEPLOY_ACEITE_APROVADO,
)
from aso.control.deploy import (
    ACEITE_REPROVADO as DEPLOY_ACEITE_REPROVADO,
)
from aso.control.deploy import (
    STATUS_FALHOU as DEPLOY_STATUS_FALHOU,
)
from aso.control.deploy import (
    STATUS_PENDENTE as DEPLOY_STATUS_PENDENTE,
)
from aso.control.deploy import (
    DeployRun,
)
from aso.control.discovery import (
    STATUS_AGUARDANDO_APROVACAO,
    STATUS_APROVADO,
    STATUS_RASCUNHO,
    STATUS_REPROVADO,
    DiscoveryReport,
)
from aso.control.failure import MARCA_DIFF_VAZIO as _EMPTY_DIFF_MARK
from aso.control.failure import FailureRecord, diagnosticar
from aso.control.models import Orchestration
from aso.control.orcamento import SITUACAO_ALERTA, SITUACAO_ESTOURADO, avaliar_orcamento
from aso.control.qa import STATUS_FALHOU as QA_STATUS_FALHOU
from aso.control.qa import exige_qa_manual
from aso.control.review import VEREDITO_ALTERACOES_OBRIGATORIAS, VEREDITO_REPROVADO
from aso.control.spec import (
    STATUS_AGUARDANDO_REVISAO as SPEC_STATUS_AGUARDANDO_REVISAO,
)
from aso.control.spec import (
    STATUS_APROVADOS as SPEC_STATUS_APROVADOS,
)
from aso.control.spec import (
    STATUS_NECESSITA_HUMANO as SPEC_STATUS_NECESSITA_HUMANO,
)
from aso.control.spec import (
    STATUS_RASCUNHO as SPEC_STATUS_RASCUNHO,
)
from aso.control.spec import (
    STATUS_REPROVADO as SPEC_STATUS_REPROVADO,
)
from aso.control.spec import (
    SpecDocument,
)
from aso.control.triage import DemandBrief
from aso.execution.docs_drift import DocsDriftReport
from aso.governance.models import (
    CandidateRun,
    Conflict,
    HumanApproval,
    PullRequest,
    QualityGateResult,
    ReviewComment,
)
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


class PhaseInfo(BaseModel):
    """O que uma etapa da esteira significa, em linguagem de operador.

    `PHASE_LABELS` guarda o nome técnico em inglês (usado nos docs e no relatório); isto
    aqui é a explicação didática que a tela mostra: "F5" sozinho não diz nada a quem abre
    o console pela primeira vez.
    """

    id: str
    label: str  # nome técnico (docs/phases/)
    nome: str  # nome curto em pt-BR
    resumo: str  # o que se faz nesta etapa
    entrega: str  # o artefato que ela produz


# Descrições genéricas — valem para qualquer projeto orquestrado, não para o
# desenvolvimento do próprio ASO (que é o que os `docs/phases/*.md` documentam).
PHASE_INFO: dict[Phase, PhaseInfo] = {
    Phase.F1: PhaseInfo(
        id="F1",
        label=PHASE_LABELS[Phase.F1],
        nome="Descoberta e estratégia",
        resumo="Entender o problema, quem usa e o que conta como sucesso.",
        entrega="Requisitos, hipóteses e critérios de valor.",
    ),
    Phase.F2: PhaseInfo(
        id="F2",
        label=PHASE_LABELS[Phase.F2],
        nome="Arquitetura e design",
        resumo="Escolher a estrutura do sistema e registrar o porquê de cada decisão.",
        entrega="ADRs, módulos e seus limites.",
    ),
    Phase.F3: PhaseInfo(
        id="F3",
        label=PHASE_LABELS[Phase.F3],
        nome="Dados e contratos",
        resumo="Definir entidades, schemas e a API pela qual as partes conversam.",
        entrega="Modelo de dados e contratos de API.",
    ),
    Phase.F4: PhaseInfo(
        id="F4",
        label=PHASE_LABELS[Phase.F4],
        nome="UX e planejamento",
        resumo="Desenhar as jornadas e quebrar o trabalho em cards executáveis.",
        entrega="Fluxos de tela e backlog priorizado.",
    ),
    Phase.F5: PhaseInfo(
        id="F5",
        label=PHASE_LABELS[Phase.F5],
        nome="Execução de engenharia",
        resumo="Escrever o código: um worktree git isolado por card, diff coletado antes do merge.",
        entrega="Branches, PRs e testes verdes.",
    ),
    Phase.F6: PhaseInfo(
        id="F6",
        label=PHASE_LABELS[Phase.F6],
        nome="Qualidade, docs e deploy",
        resumo="Testar, revisar, sincronizar a documentação e passar pelo pipeline.",
        entrega="Quality gate aprovado e docs em dia.",
    ),
    Phase.F7: PhaseInfo(
        id="F7",
        label=PHASE_LABELS[Phase.F7],
        nome="Operação e evolução",
        resumo="Observar o que está em produção e realimentar o backlog com o que aparecer.",
        entrega="Métricas, SLOs e novos cards.",
    ),
}


def phase_catalog() -> list[dict[str, Any]]:
    """A esteira inteira, para a UI montar os passos sem duplicar texto."""
    return [PHASE_INFO[fase].model_dump() for fase in Phase]


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
    demand_brief: DemandBrief = field(default_factory=DemandBrief)
    discovery_report: DiscoveryReport = field(default_factory=DiscoveryReport)
    spec: SpecDocument = field(default_factory=SpecDocument)
    deploy: DeployRun = field(default_factory=DeployRun)
    candidate_runs: list[CandidateRun] = field(default_factory=list)
    cards: list[KanbanCard] = field(default_factory=list)
    approvals: list[HumanApproval] = field(default_factory=list)
    pulls: list[PullRequest] = field(default_factory=list)
    review_comments: list[ReviewComment] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    gate_results: list[QualityGateResult] = field(default_factory=list)
    drift: DocsDriftReport | None = None
    # None = catálogo não configurado/indeterminado; False = executor indisponível.
    executor_available: bool | None = None
    executor_reason: str = ""
    slo_breaches: list[str] = field(default_factory=list)
    # Orçamento com freio (§1.2/§3.2, ADR-0026) — custo real acumulado (soma de
    # `card.uso.custo_usd`), comparado ao teto opcional da orquestração.
    gasto_usd: float = 0.0
    # Sobrevivência a crash (§1.4/§3.3, ADR-0027) — o mesmo timeout que já mata um
    # agente travado (`ASO_AGENT_TIMEOUT`) é o sinal de que ninguém mais pode estar
    # trabalhando num card parado em `InProgress` há mais tempo que isso.
    agent_timeout_seconds: float = 1800.0


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


def _demand_blockers(inp: NextStepInput) -> list[NextStepBlocker]:
    """Perguntas abertas da triagem (§1 do fluxo.md: *"poderá solicitar informações
    adicionais antes de iniciar a execução"*). `SEVERITY_HUMAN` fica abaixo de
    `SEVERITY_BLOCKS` na ordenação: aparece com destaque, mas não trava a esteira — o
    orquestrador *poderá* pedir mais informação, não *deverá* parar.
    """
    perguntas = inp.demand_brief.perguntas_abertas
    if not perguntas:
        return []
    return [
        NextStepBlocker(
            code="demanda_incompleta",
            severity=SEVERITY_HUMAN,
            title="A triagem ficou com perguntas em aberto",
            detail=" · ".join(perguntas[:3]),
        )
    ]


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
        comentarios_pr = [c for c in inp.review_comments if c.pr_id == pr.id]
        found.append(_pr_blocker(orch.id, pr, comentarios_pr))
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


def _budget_blocker(inp: NextStepInput) -> NextStepBlocker | None:
    """Orçamento com freio (§1.2/§3.2, ADR-0026). `alerta` é informativo (não trava a
    esteira); `estourado` bloqueia — a ação de elevar o teto é sempre `admin`, no
    mesmo espírito da regra 4 do CLAUDE.md: autorizar mais gasto é decisão humana."""
    orch = inp.orchestration
    situacao, motivo = avaliar_orcamento(inp.gasto_usd, orch.orcamento_usd)
    if situacao == SITUACAO_ESTOURADO:
        return NextStepBlocker(
            code="orcamento_estourado",
            severity=SEVERITY_BLOCKS,
            title="Orçamento estourado",
            detail=f"{motivo}. Novas execuções ficam recusadas até o teto subir "
            "(a que já estiver rodando não é interrompida).",
            action=NextStepAction(
                label="Elevar teto de orçamento",
                method="PUT",
                path=_orch_path(orch.id, "/budget"),
                role="admin",
            ),
        )
    if situacao == SITUACAO_ALERTA:
        return NextStepBlocker(
            code="orcamento_em_alerta",
            severity=SEVERITY_INFO,
            title="Orçamento próximo do teto",
            detail=motivo,
            action=NextStepAction(
                label="Elevar teto de orçamento",
                method="PUT",
                path=_orch_path(orch.id, "/budget"),
                role="admin",
            ),
        )
    return None


def _orphan_card_blocker(inp: NextStepInput) -> NextStepBlocker | None:
    """Card órfão (§1.4/§3.3, ADR-0027): `InProgress` parado por mais tempo que
    `ASO_AGENT_TIMEOUT` — o próprio timeout já garante que nenhum agente vivo poderia
    ainda estar nele (o provider mata e move o card fora de `InProgress` antes disso).
    Aponta para `route_card` (ADR-0019), não um caminho novo de recuperação."""
    agora = datetime.now(UTC)
    for card in inp.cards:
        if card.status != ColumnKey.IN_PROGRESS:
            continue
        try:
            parado_desde = datetime.fromisoformat(card.updated_at)
        except ValueError:
            continue
        segundos = (agora - parado_desde).total_seconds()
        if segundos < inp.agent_timeout_seconds:
            continue
        return NextStepBlocker(
            code="card_orfao",
            severity=SEVERITY_OPERATOR,
            title="Card em execução há mais tempo que o timeout do agente",
            detail=(
                f"'{card.title}' está em InProgress há {segundos / 60:.0f} min — mais que o "
                f"timeout de {inp.agent_timeout_seconds / 60:.0f} min. Provavelmente um crash "
                "de processo deixou o card preso; o roteamento decide o retorno."
            ),
            action=NextStepAction(
                label="Rotear card órfão",
                path=_orch_path(inp.orchestration.id, f"/cards/{card.id}/route"),
            ),
        )
    return None


def _pr_blocker(
    orchestration_id: str, pr: PullRequest, comentarios: list[ReviewComment]
) -> NextStepBlocker:
    """Traduz o estágio de uma PR aberta na próxima ação do merge governado.

    Ordem de checagem: CI → revisão independente (ADR-0017) → comentários
    obrigatórios pendentes (ADR-0033) → merge. O antigo `pr_review_pendente`, que
    oferecia `{"status": "approved"}` como um clique só — sem ninguém ter revisado
    — não existe mais: a revisão passa a ser um agente rodando sobre o diff real, e
    só um veredito aprovado (ou justificativa humana com papel admin) libera o merge.
    """
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
    if not pr.review_verdict:
        return NextStepBlocker(
            code="pr_review_nao_executada",
            severity=SEVERITY_OPERATOR,
            title=f"PR {pr.branch}: revisão ainda não executada",
            detail="CI verde. Rode o agente revisor sobre o diff real antes do merge.",
            action=NextStepAction(
                label="Rodar revisão",
                path=_orch_path(orchestration_id, f"/pulls/{pr.id}/review/run"),
            ),
        )
    veredito = pr.review_verdict.get("veredito")
    if veredito in (VEREDITO_ALTERACOES_OBRIGATORIAS, VEREDITO_REPROVADO):
        descricoes = [
            str(acao.get("descricao", "")) for acao in pr.review_verdict.get("acoes") or []
        ]
        detail = " · ".join(d for d in descricoes[:3] if d)
        detail = detail or "Veja o veredito completo da revisão."
        return NextStepBlocker(
            code="pr_alteracoes_obrigatorias",
            severity=SEVERITY_BLOCKS,
            title=f"PR {pr.branch}: revisão pediu alterações obrigatórias",
            detail=detail,
            action=(
                NextStepAction(
                    label="Reexecutar card",
                    path=_orch_path(orchestration_id, f"/cards/{pr.card_id}/run"),
                )
                if pr.card_id
                else None
            ),
        )
    if pr.review_status != "approved":
        # Cobre `necessita_humano`, indisponibilidade do revisor e o caso em que o
        # agente aprovou mas o risco da demanda exige confirmação humana (§4.3).
        return NextStepBlocker(
            code="pr_review_humana",
            severity=SEVERITY_HUMAN,
            title=f"PR {pr.branch}: revisão exige confirmação humana",
            detail=str(pr.review_verdict.get("fallback_reason") or "")
            or "O veredito do agente não fecha a revisão sozinho — aprove com justificativa.",
            action=NextStepAction(
                label="Aprovar com justificativa",
                path=_orch_path(orchestration_id, f"/pulls/{pr.id}/review"),
                body={"status": "approved"},
                role="admin",
            ),
        )
    comentario_pendente = next(
        (c for c in comentarios if c.obrigatorio and c.status == "pendente"), None
    )
    if comentario_pendente is not None:
        return NextStepBlocker(
            code="pr_comentario_obrigatorio_nao_resolvido",
            severity=SEVERITY_BLOCKS,
            title=f"PR {pr.branch}: comentário obrigatório não resolvido",
            detail=f"{comentario_pendente.arquivo}:{comentario_pendente.linha} — "
            f"{comentario_pendente.descricao}",
            action=NextStepAction(
                label="Resolver comentário",
                path=_orch_path(
                    orchestration_id, f"/pulls/{pr.id}/comments/{comentario_pendente.id}/resolve"
                ),
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


def _cards_falhos_blocker(orchestration_id: str, falhos: list[KanbanCard]) -> NextStepBlocker:
    """Cards em `Failed` só chegam lá via roteamento de falha (ADR-0019): a política já
    escalou para humano depois de esgotar as tentativas automáticas — daí a severidade
    `SEVERITY_HUMAN` em vez de `SEVERITY_BLOCKS` (que outros bloqueios de card usam)."""
    primeiro = falhos[0]
    detail = primeiro.block_reason or "Veja a atividade para o erro do agente."
    if primeiro.failures:
        ultimo = FailureRecord.model_validate(primeiro.failures[-1])
        diagnostico = diagnosticar(ultimo)
        # §36.4, ADR-0031: `tentativa_atual` é o contador autoritativo (nunca
        # truncado) — `len(failures)` é só o tamanho do ring, travado em 5.
        rotulo_tentativa = f"tentativa {primeiro.tentativa_atual}"
        if primeiro.max_tentativas is not None:
            rotulo_tentativa += f" de {primeiro.max_tentativas}"
        detail = f"[{diagnostico}] {detail} ({rotulo_tentativa})"
    return NextStepBlocker(
        code="cards_falhos",
        severity=SEVERITY_HUMAN,
        title=f"{len(falhos)} card(s) escalados para decisão humana",
        detail=detail,
        action=NextStepAction(
            label="Recolocar em execução", path=_orch_path(orchestration_id, "/retry")
        ),
    )


def _discovery_blocker(orch_id: str, report: DiscoveryReport) -> NextStepBlocker | None:
    """Bloqueio de discovery (§3/§4, ADR-0020) — só existe quando um relatório foi
    gerado (`status` vazio = discovery nunca rodado, não bloqueia nada)."""
    if report.status == STATUS_REPROVADO:
        return NextStepBlocker(
            code="discovery_reprovado",
            severity=SEVERITY_OPERATOR,
            title="Discovery reprovado — precisa ser ajustado",
            detail=report.revisao_comentarios or "Veja os comentários da revisão.",
            action=NextStepAction(
                label="Rodar discovery de novo", path=_orch_path(orch_id, "/discovery/run")
            ),
        )
    if report.status == STATUS_AGUARDANDO_APROVACAO:
        return NextStepBlocker(
            code="discovery_aguardando_aprovacao",
            severity=SEVERITY_HUMAN,
            title="Discovery aguardando aprovação humana",
            detail=report.recomendacao_tecnica or "Risco/confiança exigem confirmação humana.",
            action=NextStepAction(
                label="Decidir discovery",
                path=_orch_path(orch_id, "/discovery/decide"),
                role="admin",
            ),
        )
    return None


def _spec_blocker(orch_id: str, spec: SpecDocument, *, enforced: bool) -> NextStepBlocker | None:
    """Bloqueio de especificação (§5/§6, ADR-0021).

    `enforced` = True quando `run_phase` já recusa rodar F5 sem spec aprovada
    (`execution_mode == FULL_PIPELINE`) — aí a severidade é `bloqueia`, refletindo o
    que o runtime realmente impede; fora disso (ex.: `CODE_EXECUTION`), é só aviso.
    """
    if spec.status in SPEC_STATUS_APROVADOS:
        return None
    severidade = SEVERITY_BLOCKS if enforced else SEVERITY_OPERATOR
    if spec.status == SPEC_STATUS_REPROVADO:
        return NextStepBlocker(
            code="spec_reprovada",
            severity=severidade,
            title="Especificação reprovada — precisa ser ajustada",
            detail=spec.revisao_comentarios or "Veja os comentários da revisão documental.",
            action=NextStepAction(label="Gerar nova versão", path=_orch_path(orch_id, "/spec/run")),
        )
    if spec.status == SPEC_STATUS_NECESSITA_HUMANO:
        return NextStepBlocker(
            code="spec_aguardando_humano",
            severity=SEVERITY_HUMAN,
            title="Especificação aguardando decisão humana",
            detail="O ciclo de revisão documental (§6) esgotou as rodadas automáticas.",
            action=NextStepAction(
                label="Decidir especificação",
                path=_orch_path(orch_id, "/spec/approve"),
                role="admin",
            ),
        )
    if spec.status == SPEC_STATUS_AGUARDANDO_REVISAO:
        return NextStepBlocker(
            code="spec_em_revisao",
            severity=severidade,
            title="Especificação gerada, aguardando revisão documental",
            detail="Rode a revisão documental (§6) antes de liberar a execução.",
            action=NextStepAction(
                label="Rodar revisão documental", path=_orch_path(orch_id, "/spec/review")
            ),
        )
    return NextStepBlocker(  # rascunho: especificação nunca gerada
        code="spec_pendente",
        severity=severidade,
        title="Especificação ainda não gerada",
        detail="Com o discovery aprovado, gere a especificação (§5) antes de F5.",
        action=NextStepAction(label="Gerar especificação", path=_orch_path(orch_id, "/spec/run")),
    )


def _deploy_blocker(orch_id: str, deploy: DeployRun) -> NextStepBlocker | None:
    """Bloqueio de implantação (§18-22, ADR-0023; §19, ADR-0029) — só existe quando
    uma tentativa de implantação de fato ocorreu (`status` pendente = nunca
    implantou, não bloqueia nada). Com pipeline configurado, `deploy.estagio` nomeia
    o estágio no título; `diagnostico_falha`/`proxima_acao_falha` (quando presentes)
    entram no detalhe — nenhuma falha de implantação fica sem próxima ação nomeada
    (Princípio central do fluxo.md)."""
    titulo_estagio = f"Estágio '{deploy.estagio}'" if deploy.estagio else "Implantação"
    if deploy.status == DEPLOY_STATUS_FALHOU:
        return NextStepBlocker(
            code="deploy_falhou",
            severity=SEVERITY_OPERATOR,
            title=f"{titulo_estagio} falhou",
            detail=(
                deploy.proxima_acao_falha or deploy.resultado or "Veja os logs da implantação."
            ),
            action=NextStepAction(
                label="Rodar implantação de novo", path=_orch_path(orch_id, "/deploy/run")
            ),
        )
    if deploy.aceite_status == DEPLOY_ACEITE_AGUARDANDO_HUMANO:
        detail = (
            "Risco/impacto da demanda ou validação pós-implantação exigem confirmação humana (§22)."
        )
        if deploy.proxima_acao_falha:
            detail = f"{deploy.proxima_acao_falha} {detail}"
        return NextStepBlocker(
            code="deploy_aguardando_aceite",
            severity=SEVERITY_HUMAN,
            title=f"{titulo_estagio} aguardando aceite final",
            detail=detail,
            action=NextStepAction(
                label="Decidir aceite da implantação",
                path=_orch_path(orch_id, "/deploy/approve"),
                role="admin",
            ),
        )
    if deploy.aceite_status == DEPLOY_ACEITE_REPROVADO:
        return NextStepBlocker(
            code="deploy_reprovada",
            severity=SEVERITY_OPERATOR,
            title=f"{titulo_estagio} reprovado no aceite final",
            detail=(
                deploy.proxima_acao_falha
                or deploy.aceite_comentario
                or "Veja o comentário da decisão."
            ),
            action=NextStepAction(
                label="Rodar implantação de novo", path=_orch_path(orch_id, "/deploy/run")
            ),
        )
    return None


def _race_blocker(
    orch_id: str, do_ciclo: list[KanbanCard], candidate_runs: list[CandidateRun]
) -> NextStepBlocker | None:
    """§26A.6 (plano6 §0, ADR-0024): uma corrida que perdeu candidato nunca é
    silenciosa — o operador vê "recomendado: X" e precisa saber que Y nem
    competiu antes de confiar na recomendação. Só olha cards ainda não `Done`:
    uma corrida degradada num card já mesclado é histórico, não bloqueio."""
    ids_em_aberto = {c.id for c in do_ciclo if c.status != ColumnKey.DONE}
    for run in reversed(candidate_runs):
        if run.card_id not in ids_em_aberto:
            continue
        falhas = [c for c in run.candidates if c.get("error")]
        if not falhas:
            continue
        total = len(run.candidates)
        motivos = " · ".join(str(f.get("error") or "") for f in falhas[:3])
        return NextStepBlocker(
            code="corrida_degradada",
            severity=SEVERITY_OPERATOR,
            title=f"Corrida de candidatos concluiu {total - len(falhas)} de {total}",
            detail=motivos or "Veja o histórico da corrida para o motivo de cada falha.",
            action=NextStepAction(
                label="Rodar corrida de novo",
                path=_orch_path(orch_id, f"/cards/{run.card_id}/race"),
            ),
        )
    return None


def _qa_blocker(
    orch_id: str, do_ciclo: list[KanbanCard], brief: DemandBrief
) -> NextStepBlocker | None:
    """QA manual (§16/§17, ADR-0025): olha o ÚLTIMO `QaCheck` de cada card — um novo
    registro depois de uma reprovação resolve o bloqueio sozinho, sem precisar
    "fechar" o item antigo. Cards ainda não avaliados por `exige_qa_manual` não
    entram aqui: a regra é a mesma usada para exigir QA em primeiro lugar."""
    terminais = (ColumnKey.CANCELLED, ColumnKey.ARCHIVED)
    elegiveis = (ColumnKey.TESTING, ColumnKey.REVIEW, ColumnKey.DONE)
    for card in do_ciclo:
        if card.status in terminais:
            continue
        ultimo = card.qa_checks[-1] if card.qa_checks else None
        if ultimo is not None and ultimo.get("status") == QA_STATUS_FALHOU:
            return NextStepBlocker(
                code="qa_reprovado",
                severity=SEVERITY_BLOCKS,
                title=f"QA reprovado no card '{card.title}'",
                detail="A última verificação manual reprovou — corrija e registre um novo QA.",
                action=NextStepAction(
                    label="Ver QA do card", path=_orch_path(orch_id, f"/cards/{card.id}/qa")
                ),
            )
        if ultimo is None and card.status in elegiveis and exige_qa_manual(brief, card):
            return NextStepBlocker(
                code="qa_pendente",
                severity=SEVERITY_HUMAN,
                title=f"QA manual exigido para '{card.title}'",
                detail="Domínio/complexidade/tipo do card exigem verificação manual (§16) "
                "antes de seguir.",
                action=NextStepAction(
                    label="Registrar QA", path=_orch_path(orch_id, f"/cards/{card.id}/qa")
                ),
            )
    return None


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
    if phase == Phase.F1:
        discovery_blocker = _discovery_blocker(orch.id, inp.discovery_report)
        if discovery_blocker is not None:
            found.append(discovery_blocker)
    # Mesma regra de não-regressão do gate de discovery (ADR-0020 §6): só exige spec
    # quando o fluxo de discovery foi de fato usado — orquestrações full-pipeline que
    # nunca chamam /discovery/run não ganham um bloqueio novo em F5.
    discovery_em_uso = inp.discovery_report.status != STATUS_RASCUNHO
    if phase == Phase.F5 and (
        (orch.execution_mode == ExecutionMode.FULL_PIPELINE and discovery_em_uso)
        or inp.spec.status != SPEC_STATUS_RASCUNHO
    ):
        spec_blocker = _spec_blocker(
            orch.id,
            inp.spec,
            enforced=orch.execution_mode == ExecutionMode.FULL_PIPELINE and discovery_em_uso,
        )
        if spec_blocker is not None:
            found.append(spec_blocker)
    # Mesma regra de não-regressão: só aparece quando `/deploy/run` de fato rodou.
    if phase == Phase.F6 and inp.deploy.status != DEPLOY_STATUS_PENDENTE:
        deploy_blocker = _deploy_blocker(orch.id, inp.deploy)
        if deploy_blocker is not None:
            found.append(deploy_blocker)
    race_blocker = _race_blocker(orch.id, do_ciclo, inp.candidate_runs)
    if race_blocker is not None:
        found.append(race_blocker)
    qa_blocker = _qa_blocker(orch.id, do_ciclo, inp.demand_brief)
    if qa_blocker is not None:
        found.append(qa_blocker)
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
    # Desde a ADR-0019, o diagnóstico `sem_permissao` bloqueia (Blocked) em vez de
    # escalar (Failed) — verifica os dois grupos para a dica continuar aparecendo.
    if any(_EMPTY_DIFF_MARK in (c.block_reason or "") for c in (*falhos, *bloqueados)):
        # Falha silenciosa clássica: o CLI roda, sai com 0 e não escreve nada porque
        # está sem permissão de escrita. Sem esta dica o operador culpa o agente.
        found.append(
            NextStepBlocker(
                code="executor_sem_permissao",
                severity=SEVERITY_BLOCKS,
                title="O agente rodou, mas não alterou nada no worktree",
                detail=(
                    "Sintoma clássico de agente CLI sem permissão de escrita: `claude -p` "
                    "precisa de `--permission-mode acceptEdits` (ou "
                    "`--dangerously-skip-permissions`) e `codex exec` de "
                    "`--sandbox workspace-write`. Ajuste o comando do executor em "
                    "/ui/console → ⚙ Config e execute a fase de novo."
                ),
            )
        )
    if falhos:
        found.append(_cards_falhos_blocker(orch.id, falhos))
    corrigir = por_status.get(ColumnKey.NEEDS_FIX, [])
    if corrigir:
        primeiro = corrigir[0]
        acoes = primeiro.correction_actions
        found.append(
            NextStepBlocker(
                code="cards_aguardando_correcao",
                severity=SEVERITY_OPERATOR,
                title=f"{len(corrigir)} card(s) aguardando correção",
                detail=" · ".join(acoes[:3]) if acoes else "Revisão pediu alterações obrigatórias.",
                action=NextStepAction(
                    label="Reexecutar card",
                    path=_orch_path(orch.id, f"/cards/{primeiro.id}/run"),
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
    if phase == Phase.F1 and inp.discovery_report.status != STATUS_RASCUNHO:
        # Só entra quando `/discovery/run` já foi chamado ao menos uma vez (§3/§4,
        # ADR-0020) — a maioria das orquestrações nunca passa por discovery.
        itens.append(
            NextStepChecklistItem(
                code="discovery",
                state=(
                    STATE_OK if inp.discovery_report.status == STATUS_APROVADO else STATE_PENDING
                ),
                label=f"Discovery: {inp.discovery_report.status}",
            )
        )
    if phase == Phase.F5 and inp.spec.status != SPEC_STATUS_RASCUNHO:
        # Só entra quando `/spec/run` já foi chamado ao menos uma vez (§5/§6,
        # ADR-0021) — CODE_EXECUTION nunca passa por especificação.
        itens.append(
            NextStepChecklistItem(
                code="especificacao",
                state=STATE_OK if inp.spec.status in SPEC_STATUS_APROVADOS else STATE_PENDING,
                label=f"Especificação: {inp.spec.status}",
            )
        )
    if phase == Phase.F6 and inp.deploy.status != DEPLOY_STATUS_PENDENTE:
        # Só entra quando `/deploy/run` já foi chamado ao menos uma vez (§18-22,
        # ADR-0023) — a maioria das orquestrações nunca implanta pelo runtime.
        itens.append(
            NextStepChecklistItem(
                code="implantacao",
                state=(
                    STATE_OK
                    if inp.deploy.aceite_status == DEPLOY_ACEITE_APROVADO
                    else STATE_PENDING
                ),
                label=f"Implantação ({inp.deploy.ambiente}): {inp.deploy.aceite_status}",
            )
        )
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
        *_demand_blockers(inp),
        *_governance_blockers(inp),
        *_card_blockers(inp, phase),
        *_gate_blockers(inp, phase),
    ]
    budget_blocker = _budget_blocker(inp)
    if budget_blocker is not None:
        blockers.append(budget_blocker)
    orphan_blocker = _orphan_card_blocker(inp)
    if orphan_blocker is not None:
        blockers.append(orphan_blocker)
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
