"""`DeliveryService` — entrega governada extraída do `OrchestrationService` (ADR-0066).

MEL-32, passo 3: abrir PR, CI (executada/declarada, ADR-0056), revisão independente
(ADR-0017), comentários obrigatórios e merge governado (regra inviolável 6).
"""

from __future__ import annotations

import os
import shlex
import threading
from collections.abc import Callable
from typing import Any

from aso.application.agent_task import AgentTaskService
from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.control.discovery import DiscoveryReport
from aso.control.documentos import versao_atual
from aso.control.failure import ETAPA_CI, FailureRecord, registrar
from aso.control.models import REVIEW_KEY, AgentAssignment
from aso.control.review import (
    VEREDITO_ALTERACOES_OBRIGATORIAS,
    VEREDITO_APROVADO,
    VEREDITO_APROVADO_COM_SUGESTOES,
    VEREDITO_REPROVADO,
    ReviewService,
    ReviewVerdict,
    exige_confirmacao_humana,
)
from aso.control.spec import SpecDocument
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog
from aso.execution.code_index import arquivos_do_diff, indice_para_uso
from aso.execution.impacto import ImpactoEstrutural, impacto_de
from aso.execution.repositorio_leitura import AcessoAoRepositorio
from aso.execution.worktree import WorktreeError, WorktreeManager
from aso.governance.models import PullRequest, ReviewComment
from aso.kanban.models import KanbanCard
from aso.shared.ids import now_iso
from aso.shared.types import CardType, ColumnKey


def _build_card_closure(
    b: OrchestrationBundle, card: KanbanCard, pr: PullRequest
) -> dict[str, Any]:
    """Ficha de encerramento do card (§23 do fluxo.md, ADR-0021) — preenchida no
    merge, o ponto em que o card chega a Done. Só registra o que o runtime já tem à
    mão: campo sem dado disponível (data de implantação, commits individuais) fica de
    fora — ficha com campo inventado é pior que ficha curta."""
    acoes = pr.review_verdict.get("acoes") if pr.review_verdict else []
    riscos_residuais = [
        str(a.get("descricao", "")) for a in (acoes or []) if a.get("severidade") == "sugestao"
    ]
    documentos: dict[str, int] = {}
    if b.orchestration.discovery_reports:
        documentos["discovery_versao"] = versao_atual(
            b.orchestration.discovery_reports, DiscoveryReport
        ).versao
    if b.orchestration.spec_documents:
        documentos["spec_versao"] = versao_atual(
            b.orchestration.spec_documents, SpecDocument
        ).versao
    return {
        "resumo": pr.title or card.title,
        "executor": card.executor or "",
        "revisor": pr.reviewed_by,
        "branch": pr.branch,
        "pr_id": pr.id,
        "rodadas_revisao": pr.review_rounds,
        "documentos": documentos,
        # Origem da CI (ADR-0056): "passed (declarada)" não é a mesma evidência que
        # "passed (executada)" — a ficha precisa dizer qual das duas liberou o merge.
        "ci_origem": pr.ci_origem or "desconhecida",
        "evidencias": [
            f"CI: {pr.ci_status} ({pr.ci_origem or 'desconhecida'})",
            f"Revisão: {pr.review_status}",
        ],
        "riscos_residuais": riscos_residuais,
        # Checklist de preparação (§10, ADR-0030) — evidência de que os itens do
        # §10 foram marcados durante a execução, não só implicitamente.
        "checklist_preparacao": card.preparation_checklist,
        # §23 pede "effort utilizado"; custo real (§1.1, ADR-0026) responde a mesma
        # pergunta em dinheiro. `card.uso` vazio (executor que nunca informou uso)
        # não aparece como zero — o campo some, ficha curta é melhor que inventada.
        **({"custo_usd": card.uso["custo_usd"]} if card.uso.get("custo_usd") else {}),
        **({"modelo": card.uso["modelo"]} if card.uso.get("modelo") else {}),
        "encerrado_em": now_iso(),
    }


def _ultima_saida_de_ci(b: OrchestrationBundle, pr: PullRequest) -> str:
    """Status, origem e saída da CI mais recente da PR (vazio se nunca rodou)."""
    for evento in reversed(b.event_log.all()):
        if evento.type == "CIReported" and evento.payload.get("pr_id") == pr.id:
            detalhe = str(evento.payload.get("detail") or "")
            origem = evento.payload.get("origem", "")
            return f"status: {evento.payload.get('status')} (origem: {origem})\n{detalhe}".strip()
    return ""


def _impacto_do_diff(repositorio: str, diff: str) -> ImpactoEstrutural | None:
    """Impacto estrutural dos arquivos do diff (ADR-0077); `None` quando não há índice."""
    arquivos = arquivos_do_diff(diff)
    if not arquivos:
        return None
    indice = indice_para_uso(repositorio)
    return impacto_de(indice, arquivos) if indice is not None else None


class DeliveryService:
    """Entrega governada: PR, CI executada/declarada, revisão independente e merge."""

    def __init__(
        self,
        store: BundleStore,
        *,
        review: ReviewService,
        log: Any,
        catalogo: Callable[[], ExecutorCatalog | None],
        assignment: Callable[[OrchestrationBundle, str | None], AgentAssignment | None],
        workspace_for: Callable[[OrchestrationBundle], WorktreeManager],
        perguntar_registrando: Callable[..., Any],
    ) -> None:
        self._bundle_store = store
        self._review = review
        self._log = log
        self._catalogo = catalogo
        self._assignment_de = assignment
        self._workspace_de = workspace_for
        self._perguntar = perguntar_registrando

    # Colaboradores injetados (o catálogo é lido a cada uso: a façade pode trocá-lo).
    @property
    def _catalog(self) -> ExecutorCatalog | None:
        return self._catalogo()

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    def _assignment(self, b: OrchestrationBundle, key: str | None) -> AgentAssignment | None:
        return self._assignment_de(b, key)

    def _workspace_for(self, b: OrchestrationBundle) -> WorktreeManager:
        return self._workspace_de(b)

    def _perguntar_registrando(
        self, orchestration_id: str, card_id: str | None, chamada: Callable[[], Any]
    ) -> Any:
        return self._perguntar(orchestration_id, card_id, chamada)

    # ------------------------------------------------- Pull Requests (§26, MVP-4)
    def open_pr(
        self, orchestration_id: str, card_id: str, *, branch: str | None = None, title: str = ""
    ) -> PullRequest:
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.get_card(card_id)
            if card is None:
                raise KeyError(f"Card inexistente: {card_id}")
            selected_branch = branch or card.branch
            if not selected_branch and b.orchestration.validation_command:
                raise ValueError("Card sem branch candidata para abrir PR.")
            if not selected_branch:
                selected_branch = f"aso/{card_id}"  # compatibilidade com o provider mock legado
            if (
                b.orchestration.validation_command
                and not self._workspace_for(b).branch_diff(selected_branch).strip()
            ):
                raise ValueError("Não é possível abrir PR sem alterações na branch candidata.")
            pr = PullRequest(
                orchestration_id=orchestration_id,
                card_id=card_id,
                branch=selected_branch,
                title=title or card.title,
            )
            b.pull_requests.append(pr)
            b.board_service.apply_event(card_id, "PROpened")  # → Review
            b.event_log.append(
                "PROpened", {"pr_id": pr.id, "branch": pr.branch, "card_id": card_id}
            )
            self._persist(b)
            return pr

    def _find_pr(self, b: OrchestrationBundle, pr_id: str) -> PullRequest:
        pr = next((p for p in b.pull_requests if p.id == pr_id), None)
        if pr is None:
            raise KeyError(f"PR inexistente: {pr_id}")
        return pr

    def report_ci(
        self,
        orchestration_id: str,
        pr_id: str,
        status: str,
        *,
        actor: str = "system",
        justificativa: str = "",
    ) -> PullRequest:
        """Registra uma CI **declarada** (ADR-0056) — o resultado não foi executado aqui.

        Regra inviolável 6: o merge confia em `ci_status == "passed"`; por isso declarar
        `passed` exige `justificativa` humana não vazia (a rota exige papel admin — a
        checagem fina fica no handler, como em `report_review`) e fica rastreado em
        `ci_origem = "declarada"` + evento `CIDeclared`. Declarar `failed` é seguro
        (só bloqueia) e continua livre.

        CI reprovada é corrigível: o card volta para `NeedsFix` com o motivo no
        nudge da próxima tentativa (§13 do fluxo.md, ADR-0019) — distinto de `Failed`,
        reservado ao roteamento de execução que decidiu escalar para humano."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            pr = self._find_pr(b, pr_id)
            if status == "passed" and not justificativa.strip():
                raise ValueError(
                    "Declarar CI 'passed' sem executá-la exige justificativa humana (papel "
                    "admin) — prefira rodar a CI real em POST .../ci/run."
                )
            pr.ci_status = status
            pr.ci_origem = "declarada"
            if status == "failed" and pr.card_id:
                card = b.board_service.get_card(pr.card_id)
                if card is not None:
                    record = FailureRecord(
                        etapa=ETAPA_CI,
                        tentativa=len(card.failures) + 1,
                        comando=pr.branch,
                        mensagem=f"CI reprovada na branch {pr.branch}",
                        executor=card.executor or "",
                    )
                    card.failures = registrar(card.failures, record)
                    card.correction_actions = [
                        "A CI reprovou na tentativa anterior — corrija o que a validação "
                        "apontou antes de reenviar."
                    ]
                    b.board_service.apply_event(pr.card_id, "CIFailed")  # → NeedsFix
            b.event_log.append(
                "CIDeclared",
                {"pr_id": pr_id, "status": status, "actor": actor, "justificativa": justificativa},
            )
            b.event_log.append(
                "CIReported", {"pr_id": pr_id, "status": status, "origem": "declarada"}
            )
            self._persist(b)
            return pr

    def report_review(
        self,
        orchestration_id: str,
        pr_id: str,
        status: str,
        *,
        actor: str = "system",
        justificativa: str = "",
    ) -> PullRequest:
        """Registra o resultado da revisão — governado (ADR-0017).

        `status == "approved"` só é aceito com um veredito aprovado já registrado
        (via `run_review`) ou com `justificativa` humana não vazia (a rota exige
        papel admin nesse caso — a checagem fina é feita no handler da API). Sem
        nenhum dos dois, o clique que "aprovava" sem ninguém ter revisado deixa
        de existir.

        Risco alto (ou impacto sensível — `exige_confirmacao_humana`, §4/§14) não fecha
        com o veredito do agente sozinho, mesmo aprovado: a confirmação humana precisa
        ser uma decisão registrada (justificativa), não um clique (ADR-0019, pendência
        da ADR-0017 — sem isto, o gate de risco segurava em `pending` e qualquer
        `operator` soltava em seguida sem que `required_role` percebesse).
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            pr = self._find_pr(b, pr_id)
            if status == "approved":
                brief = DemandBrief.model_validate(b.orchestration.demand_brief)
                exige_humano = exige_confirmacao_humana(brief)
                veredito = pr.review_verdict.get("veredito") if pr.review_verdict else None
                veredito_aprovado = veredito in (VEREDITO_APROVADO, VEREDITO_APROVADO_COM_SUGESTOES)
                if (exige_humano or not veredito_aprovado) and not justificativa.strip():
                    if not veredito_aprovado:
                        motivo = (
                            "Aprovação exige um veredito de revisão aprovado ou "
                            "justificativa humana (papel admin) — rode a revisão antes "
                            "de aprovar."
                        )
                    else:
                        motivo = (
                            "O risco da demanda exige confirmação humana registrada: "
                            "aprove com justificativa (papel admin) mesmo com o veredito "
                            "do agente aprovado."
                        )
                    raise ValueError(motivo)
                if pr.card_id:
                    card = b.board_service.get_card(pr.card_id)
                    if card is not None:
                        card.correction_actions = []
            pr.review_status = status
            if (
                status == "changes_requested"
                and pr.card_id
                and b.board_service.get_card(pr.card_id)
            ):
                b.board_service.apply_event(pr.card_id, "ReviewRequestedChanges")  # → NeedsFix
            b.event_log.append(
                "ReviewReported",
                {"pr_id": pr_id, "status": status, "actor": actor, "justificativa": justificativa},
            )
            self._persist(b)
            return pr

    def _resolve_reviewer(
        self, b: OrchestrationBundle, *, origem_executor: str | None, explicit: str | None
    ) -> tuple[str | None, str]:
        """Resolve o executor revisor: explícito → etapa 'revisao' → default do
        catálogo — desde que DIFERENTE do executor que produziu o que está sendo
        revisado (código, §14; ou documento, §6, ADR-0021).

        Devolve `(executor, "")` quando resolvido, ou `(None, motivo)` quando não
        há revisor independente disponível — nunca aprova por omissão.
        """
        candidato = explicit
        if candidato is None:
            assignment = self._assignment(b, REVIEW_KEY)
            candidato = assignment.executor if assignment is not None else None
        if candidato is None and self._catalog is not None:
            candidato = self._catalog.default_name()
        if candidato is None:
            return None, "nenhum agente revisor configurado"
        if origem_executor is not None and candidato == origem_executor:
            return None, "revisor seria o mesmo executor que produziu o que está sendo revisado"
        return candidato, ""

    def get_review(self, orchestration_id: str, pr_id: str) -> ReviewVerdict:
        """Veredito completo da última revisão (vazio = ainda não revisada)."""
        b = self._bundle(orchestration_id)
        pr = self._find_pr(b, pr_id)
        if pr.review_verdict:
            return ReviewVerdict.model_validate(pr.review_verdict)
        return ReviewVerdict()

    def run_review(
        self,
        orchestration_id: str,
        pr_id: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
        actor: str = "system",
    ) -> PullRequest:
        """Roda o agente revisor sobre o diff real da PR e aplica o veredito (ADR-0017)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            pr = self._find_pr(b, pr_id)
            if not pr.card_id:
                raise ValueError("PR sem card associado: a revisão exige o card de origem.")
            card = b.board_service.get_card(pr.card_id)
            if card is None:
                raise KeyError(f"Card inexistente: {pr.card_id}")
            if card.status == ColumnKey.NEEDS_FIX:
                raise ValueError(
                    "Card em 'Aguardando correção' — o ciclo obrigatório do wf §19.2 "
                    "exige passar pelos testes automáticos antes de uma nova revisão "
                    "(mova o card para Testing e rode os testes primeiro)."
                )
            revisor, recusa = self._resolve_reviewer(
                b, origem_executor=card.executor, explicit=executor
            )
            if recusa:
                verdito = ReviewVerdict(fallback_reason=recusa)
            else:
                assert revisor is not None  # noqa: S101 - garantido por _resolve_reviewer
                assignment_ref = self._assignment(b, REVIEW_KEY)
                efetivo_effort = effort or (assignment_ref.effort if assignment_ref else None)
                assignment = AgentAssignment(executor=revisor, effort=efetivo_effort)
                workspace = self._workspace_for(b)
                diff = workspace.branch_diff(pr.branch)
                brief = DemandBrief.model_validate(b.orchestration.demand_brief)
                # Insumos do §14 além do diff (ADR-0069): spec de origem, ADRs e última CI.
                fontes = AgentTaskService._fontes_do_contexto(b, card)
                verdito = self._perguntar_registrando(
                    b.orchestration.id,
                    pr.card_id,
                    lambda: self._review.revisar(
                        assignment,
                        diff=diff,
                        card_title=card.title,
                        card_description=card.description,
                        acceptance_criteria=card.acceptance_criteria,
                        riscos=brief.riscos,
                        item_de_spec=fontes.item_de_spec,
                        adrs=[(a.id, a.titulo, a.decisao) for a in fontes.adrs],
                        saida_ci=_ultima_saida_de_ci(b, pr),
                        repositorio=AcessoAoRepositorio(caminho=str(workspace.base), ref=pr.branch),
                        # Risco de regressão com fato: quem importa o alterado e que testes
                        # o cobrem, pelo índice do repositório (ADR-0077).
                        impacto=_impacto_do_diff(str(workspace.base), diff),
                    ),
                )
            return self._apply_review_verdict(b, pr, card, verdito, actor=actor)

    def _apply_review_verdict(
        self,
        b: OrchestrationBundle,
        pr: PullRequest,
        card: KanbanCard,
        verdito: ReviewVerdict,
        *,
        actor: str,
    ) -> PullRequest:
        """Traduz o veredito em `review_status` (§4.3 da ADR-0017: risco decide se a
        aprovação do agente fecha sozinha) e move o card reprovado para NeedsFix.

        ADR-0033: cada comentário ancorado (`verdito.comentarios`) vira um
        `ReviewComment` de primeira classe desta rodada. Rodada aprovada
        auto-resolve os comentários obrigatórios pendentes da PR (§15: correção →
        testes → nova revisão →(aprovado) próxima etapa — a resolução acontece pelo
        ciclo, não por um clique à parte); a resolução manual continua disponível
        via `resolve_review_comment` para o caso de override humano.
        """
        brief = DemandBrief.model_validate(b.orchestration.demand_brief)
        pr.review_verdict = verdito.model_dump(mode="json")
        pr.reviewed_by = verdito.revisor
        pr.review_rounds += 1
        novos_comentarios = [
            ReviewComment(
                orchestration_id=b.orchestration.id,
                pr_id=pr.id,
                card_id=card.id,
                arquivo=draft.arquivo,
                linha=draft.linha,
                categoria=draft.categoria,
                severidade=draft.severidade,
                descricao=draft.descricao,
                sugestao=draft.sugestao,
                obrigatorio=draft.obrigatorio,
                review_round=pr.review_rounds,
            )
            for draft in verdito.comentarios
        ]
        b.review_comments.extend(novos_comentarios)
        comentarios_da_pr = [c for c in b.review_comments if c.pr_id == pr.id]
        aprovado = verdito.veredito in (VEREDITO_APROVADO, VEREDITO_APROVADO_COM_SUGESTOES)
        reprovado = verdito.veredito in (VEREDITO_ALTERACOES_OBRIGATORIAS, VEREDITO_REPROVADO)
        if aprovado and not exige_confirmacao_humana(brief):
            pr.review_status = "approved"
            card.correction_actions = []
            for comentario in comentarios_da_pr:
                if comentario.status == "pendente":
                    comentario.status = "resolvido"
                    comentario.resolved_by = "system"
                    comentario.resolved_at = now_iso()
        elif reprovado:
            pr.review_status = "changes_requested"
            # Bug real (code-review ultra): o fallback para `verdito.acoes` só
            # disparava quando a PR nunca tinha comentário nenhum — uma PR com
            # comentários ANTIGOS já resolvidos (`comentarios_da_pr` não-vazio, mas
            # nenhum pendente/obrigatório) fazia a comprehension abaixo dar `[]`,
            # descartando as ações do veredito atual e deixando NeedsFix sem
            # orientação nenhuma. Agora o fallback olha o resultado FILTRADO, não a
            # existência histórica de comentários.
            pendentes_obrigatorios = [
                c.descricao for c in comentarios_da_pr if c.obrigatorio and c.status == "pendente"
            ]
            card.correction_actions = pendentes_obrigatorios or [
                acao.descricao for acao in verdito.acoes if acao.severidade == "obrigatoria"
            ]
            b.board_service.apply_event(card.id, "ReviewRequestedChanges")  # → NeedsFix
        else:  # aprovado que exige humano, ou necessita_humano
            pr.review_status = "pending"
        b.event_log.append(
            "ReviewRunCompleted",
            {
                "pr_id": pr.id,
                "actor": actor,
                "veredito": verdito.veredito,
                "origem": verdito.origem,
                "revisor": verdito.revisor,
                "review_status": pr.review_status,
            },
        )
        self._persist(b)
        return pr

    def merge_pr(self, orchestration_id: str, pr_id: str) -> PullRequest:
        """Merge governado: exige CI passed + review approved (§26A.6)."""
        # Lock por orquestração: o check-then-act (verifica status → muta → merge git)
        # precisa ser atômico para dois merges concorrentes não mesclarem em dobro.
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            pr = self._find_pr(b, pr_id)
            if pr.status != "open":
                raise ValueError(f"PR {pr_id} não está aberta (status={pr.status}).")
            if pr.ci_status != "passed" or pr.review_status != "approved":
                raise ValueError(
                    "Merge governado exige CI 'passed' e review 'approved' "
                    f"(ci={pr.ci_status}, review={pr.review_status})."
                )
            pendente = next(
                (
                    c
                    for c in b.review_comments
                    if c.pr_id == pr_id and c.obrigatorio and c.status == "pendente"
                ),
                None,
            )
            if pendente is not None:
                raise ValueError(
                    "Merge governado exige que todo comentário obrigatório do review "
                    f"esteja resolvido — pendente em {pendente.arquivo}:{pendente.linha}."
                )
            # Mensagem com o que foi entregue: `git log` da branch base precisa contar a
            # história sozinho, e "aso: merge governado" em todo merge não conta nada.
            titulo = (pr.title or "").strip()
            try:
                self._workspace_for(b).merge(
                    pr.branch,
                    message=f"aso: merge {pr.branch}" + (f" — {titulo}" if titulo else ""),
                )
            except WorktreeError as exc:
                # Falha de merge nunca é silenciosa (ADR-0062): evento com o erro, PR e card
                # continuam abertos para correção.
                alvo = b.board_service.get_card(pr.card_id) if pr.card_id else None
                evento = (
                    "DocsMergeFailed"
                    if alvo is not None and alvo.type == CardType.DOCUMENTATION
                    else "MergeFailed"
                )
                b.event_log.append(
                    evento, {"pr_id": pr_id, "branch": pr.branch, "erro": str(exc)[:500]}
                )
                self._persist(b)
                raise ValueError(f"Merge de {pr.branch} falhou: {exc}") from exc
            pr.status = "merged"
            pr.merged_at = now_iso()
            card = b.board_service.get_card(pr.card_id) if pr.card_id else None
            if card is not None and pr.card_id is not None:
                card.closure = _build_card_closure(b, card, pr)
                b.board_service.apply_event(pr.card_id, "QualityGatePassed")  # → Done
            b.event_log.append("PRMerged", {"pr_id": pr_id, "branch": pr.branch})
            self._persist(b)
        self._log.info(
            "pr_merged", orchestration_id=orchestration_id, pr_id=pr_id, branch=pr.branch
        )
        return pr

    def run_pr_ci(self, orchestration_id: str, pr_id: str) -> PullRequest:
        """Executa a validação configurada na branch candidata da PR."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            pr = self._find_pr(b, pr_id)
            command = b.orchestration.validation_command or os.environ.get("ASO_GATE_TEST_COMMAND")
            if not command:
                raise ValueError("Configure o comando de validação antes de rodar a CI.")
            ok, detail = self._workspace_for(b).run_on_branch(pr.branch, shlex.split(command))
            pr.ci_status = "passed" if ok else "failed"
            pr.ci_origem = "executada"
            b.event_log.append(
                "CIReported",
                {"pr_id": pr_id, "status": pr.ci_status, "origem": "executada", "detail": detail},
            )
            self._persist(b)
            return pr

    def resolve_review_comment(
        self, orchestration_id: str, pr_id: str, comment_id: str, *, actor: str = "system"
    ) -> ReviewComment:
        """Resolução manual de um comentário (ADR-0033) — override humano além da
        auto-resolução que já acontece quando uma rodada de review aprova."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            comment = next(
                (c for c in b.review_comments if c.id == comment_id and c.pr_id == pr_id), None
            )
            if comment is None:
                raise KeyError(f"Comentário inexistente: {comment_id}")
            if comment.status == "resolvido":
                raise ValueError("Comentário já resolvido.")
            comment.status = "resolvido"
            comment.resolved_by = actor
            comment.resolved_at = now_iso()
            self._persist(b)
            return comment
