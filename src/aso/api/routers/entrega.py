"""Rotas de entrega: pull requests, CI, revisão e merge governado.

Extraídas do `create_app` monolítico no MEL-32 passo 10 (ADR-0066).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from aso.api.deps import ApiDeps, actor_de
from aso.api.execucao_assincrona import OP_REVIEW
from aso.api.schemas import (
    CIStatusBody,
    ReviewStatusBody,
    RunReviewBody,
)


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()
    svc = deps.svc

    @router.get("/v1/orchestrations/{orchestration_id}/pulls")
    def list_pulls(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.list_pulls(orchestration_id)

    @router.post("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/ci")
    def report_ci(orchestration_id: str, pr_id: str, body: CIStatusBody, request: Request) -> Any:
        """Declara o resultado da CI sem executá-la (ADR-0056, regra inviolável 6).

        `passed` libera merge, então declará-lo é decisão humana crítica: exige papel
        admin — `required_role` não enxerga o corpo, a checagem fina fica aqui (mesmo
        padrão de `report_review`). `failed` só bloqueia e segue aberto a operator.
        """
        if body.status == "passed" and not request.state.principal.can("admin"):
            raise HTTPException(
                status_code=403,
                detail="Declarar CI 'passed' sem executá-la exige papel admin.",
            )
        return deps.card_op(
            orchestration_id,
            lambda: svc.report_ci(
                orchestration_id,
                pr_id,
                body.status,
                actor=actor_de(request),
                justificativa=body.justificativa,
            ),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/ci/run")
    def run_pr_ci(orchestration_id: str, pr_id: str) -> Any:
        return deps.card_op(orchestration_id, lambda: svc.run_pr_ci(orchestration_id, pr_id))

    @router.post("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/review/run")
    def run_review(orchestration_id: str, pr_id: str, body: RunReviewBody, request: Request) -> Any:
        """Roda o agente revisor sobre o diff real da PR e aplica o veredito (ADR-0017)."""
        if deps.fila is not None:
            deps.guard(orchestration_id)
            parametros = {"pr_id": pr_id, **body.model_dump(mode="json")}
            return deps.enfileirar(OP_REVIEW, orchestration_id, request, parametros=parametros)
        return deps.card_op(
            orchestration_id,
            lambda: svc.run_review(
                orchestration_id,
                pr_id,
                executor=body.executor,
                effort=body.effort,
                actor=actor_de(request),
            ),
        )

    @router.get("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/review")
    def get_review(orchestration_id: str, pr_id: str) -> Any:
        """Veredito completo da última revisão independente (fluxo §14)."""
        return deps.card_op(orchestration_id, lambda: svc.get_review(orchestration_id, pr_id))

    @router.post("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/review")
    def report_review(
        orchestration_id: str, pr_id: str, body: ReviewStatusBody, request: Request
    ) -> Any:
        """Reporta o resultado da revisão (governado, ADR-0017).

        Sobrepor com `justificativa` (sem veredito aprovado) é uma decisão humana que
        recusa/ignora o agente revisor: exige papel admin — `required_role` não enxerga
        o corpo da requisição, então a checagem fina do papel fica aqui.
        """
        if body.justificativa.strip() and not request.state.principal.can("admin"):
            raise HTTPException(
                status_code=403,
                detail="Aprovar com justificativa (sem veredito aprovado) exige papel admin.",
            )
        return deps.card_op(
            orchestration_id,
            lambda: svc.report_review(
                orchestration_id,
                pr_id,
                body.status,
                actor=actor_de(request),
                justificativa=body.justificativa,
            ),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/merge")
    def merge_pr(orchestration_id: str, pr_id: str) -> Any:
        deps.guard(orchestration_id)
        try:
            return svc.merge_pr(orchestration_id, pr_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    # --- comentários de revisão ancorados em arquivo/linha (wf §20.3, ADR-0033) ---

    @router.get("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/comments")
    def list_review_comments(orchestration_id: str, pr_id: str) -> Any:
        """Comentários da PR — alimenta a lista de correções obrigatórias da tela 19."""
        return deps.card_op(
            orchestration_id, lambda: svc.list_review_comments(orchestration_id, pr_id)
        )

    @router.post(
        "/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/comments/{comment_id}/resolve"
    )
    def resolve_review_comment(
        orchestration_id: str, pr_id: str, comment_id: str, request: Request
    ) -> Any:
        """Resolução manual — além da auto-resolução quando uma rodada aprova."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.resolve_review_comment(
                orchestration_id, pr_id, comment_id, actor=actor_de(request)
            ),
        )

    return router
