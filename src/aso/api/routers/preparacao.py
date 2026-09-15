"""Rotas de preparação: discovery, especificação e documentos.

Extraídas do `create_app` monolítico no MEL-32 passo 10 (ADR-0066).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from aso.api.deps import ApiDeps, actor_de
from aso.api.execucao_assincrona import OP_DISCOVERY, OP_SPEC, OP_SPEC_REVIEW
from aso.api.schemas import (
    DiscoveryDecideBody,
    DiscoveryRunBody,
    DocumentoCommentBody,
    DocumentoCommentResolveBody,
    DocumentoReviewBody,
    DocumentoSaveBody,
    SpecApproveBody,
    SpecReviewBody,
    SpecRunBody,
)


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()
    svc = deps.svc

    @router.get("/v1/orchestrations/{orchestration_id}/discovery")
    def get_discovery(orchestration_id: str) -> Any:
        """Relatório de discovery atual (§3 do fluxo.md, ADR-0020)."""
        deps.guard(orchestration_id)
        return svc.get_discovery_report(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/discovery/history")
    def get_discovery_history(orchestration_id: str) -> Any:
        """Histórico de versões do discovery (§4.2, ADR-0021) — ring de até 5."""
        deps.guard(orchestration_id)
        return svc.get_discovery_history(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/discovery/approval-criteria")
    def get_discovery_approval_criteria(orchestration_id: str) -> Any:
        """Tela 07 (wf §9, ADR-0045): checklist de critérios + motivos da escalada."""
        deps.guard(orchestration_id)
        return svc.get_discovery_approval_criteria(orchestration_id)

    @router.post("/v1/orchestrations/{orchestration_id}/discovery/run")
    def run_discovery(orchestration_id: str, body: DiscoveryRunBody, request: Request) -> Any:
        """Roda o discovery e aplica a regra de aprovação automática/humana (§4)."""
        if deps.fila is not None:
            deps.guard(orchestration_id)
            return deps.enfileirar(
                OP_DISCOVERY, orchestration_id, request, parametros=body.model_dump(mode="json")
            )
        return deps.card_op(
            orchestration_id,
            lambda: svc.run_discovery(orchestration_id, executor=body.executor, effort=body.effort),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/discovery/decide")
    def decide_discovery(orchestration_id: str, body: DiscoveryDecideBody, request: Request) -> Any:
        """Decide a aprovação humana do discovery (ação crítica — papel admin)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.decide_discovery(
                orchestration_id,
                approved=body.approved,
                comentario=body.comentario,
                actor=actor_de(request),
            ),
        )

    @router.get("/v1/orchestrations/{orchestration_id}/spec")
    def get_spec(orchestration_id: str) -> Any:
        """Especificação corrente (§5 do fluxo.md, ADR-0021)."""
        deps.guard(orchestration_id)
        return svc.get_spec(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/spec/history")
    def get_spec_history(orchestration_id: str) -> Any:
        """Histórico de versões da especificação (§4.2, ADR-0021) — ring de até 5."""
        deps.guard(orchestration_id)
        return svc.get_spec_history(orchestration_id)

    @router.post("/v1/orchestrations/{orchestration_id}/spec/run")
    def run_spec(orchestration_id: str, body: SpecRunBody, request: Request) -> Any:
        """Gera/regenera a especificação — exige discovery aprovado (§5)."""
        if deps.fila is not None:
            deps.guard(orchestration_id)
            return deps.enfileirar(
                OP_SPEC, orchestration_id, request, parametros=body.model_dump(mode="json")
            )
        return deps.card_op(
            orchestration_id,
            lambda: svc.run_spec(orchestration_id, executor=body.executor, effort=body.effort),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/spec/review")
    def run_spec_review(orchestration_id: str, body: SpecReviewBody, request: Request) -> Any:
        """Roda a revisão documental (§6) sobre a especificação corrente."""
        if deps.fila is not None:
            deps.guard(orchestration_id)
            return deps.enfileirar(
                OP_SPEC_REVIEW, orchestration_id, request, parametros=body.model_dump(mode="json")
            )
        return deps.card_op(
            orchestration_id,
            lambda: svc.run_spec_review(
                orchestration_id, executor=body.executor, actor=actor_de(request)
            ),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/spec/approve")
    def approve_spec(orchestration_id: str, body: SpecApproveBody, request: Request) -> Any:
        """Decide a especificação quando o ciclo do §6 escalou (ação crítica — admin)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.approve_spec(
                orchestration_id,
                approved=body.approved,
                comentario=body.comentario,
                actor=actor_de(request),
            ),
        )

    # ---- Documentos (Tela 08/09, wf §10/§11, ADR-0046) -----------------------

    @router.get("/v1/orchestrations/{orchestration_id}/documentos")
    def list_documentos(orchestration_id: str) -> Any:
        """Lista de documentos (wf §10.2) — os 8 tipos novos + os 5 já cobertos
        pela especificação, em modo leitura."""
        deps.guard(orchestration_id)
        return svc.list_documentos(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/documentos/{tipo}")
    def get_documento(orchestration_id: str, tipo: str) -> Any:
        return deps.documento_op(
            orchestration_id, lambda: svc.get_documento(orchestration_id, tipo)
        )

    @router.get("/v1/orchestrations/{orchestration_id}/documentos/{tipo}/history")
    def get_documento_history(orchestration_id: str, tipo: str) -> Any:
        """Histórico de versões (wf §10.3) — ring de até 5."""
        return deps.documento_op(
            orchestration_id, lambda: svc.get_documento_history(orchestration_id, tipo)
        )

    @router.get("/v1/orchestrations/{orchestration_id}/documentos/{tipo}/diff")
    def diff_documento(orchestration_id: str, tipo: str, de: int, para: int) -> Any:
        """Comparação de versões (wf §10.3)."""
        return deps.documento_op(
            orchestration_id,
            lambda: svc.diff_documento(orchestration_id, tipo, de=de, para=para),
        )

    @router.put("/v1/orchestrations/{orchestration_id}/documentos/{tipo}")
    def save_documento(orchestration_id: str, tipo: str, body: DocumentoSaveBody) -> Any:
        """Salva uma nova versão (edição manual, wf §10.3)."""
        return deps.documento_op(
            orchestration_id,
            lambda: svc.save_documento(
                orchestration_id,
                tipo,
                conteudo_markdown=body.conteudo_markdown,
                autor=body.autor,
                referencias_codigo=body.referencias_codigo,
                referencias_cards=body.referencias_cards,
                referencias_documentos=body.referencias_documentos,
            ),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/documentos/{tipo}/review")
    def review_documento(
        orchestration_id: str, tipo: str, body: DocumentoReviewBody, request: Request
    ) -> Any:
        """Checklist do revisor (wf §11) — os quatro desfechos do §11.2."""
        return deps.documento_op(
            orchestration_id,
            lambda: svc.review_documento(
                orchestration_id, tipo, executor=body.executor, actor=actor_de(request)
            ),
        )

    @router.get("/v1/orchestrations/{orchestration_id}/documentos/{tipo}/comments")
    def list_documento_comments(orchestration_id: str, tipo: str) -> Any:
        return deps.documento_op(
            orchestration_id, lambda: svc.list_documento_comments(orchestration_id, tipo)
        )

    @router.post(
        "/v1/orchestrations/{orchestration_id}/documentos/{tipo}/comments", status_code=201
    )
    def create_documento_comment(
        orchestration_id: str, tipo: str, body: DocumentoCommentBody, request: Request
    ) -> Any:
        """Comentário ancorado (wf §10.3/§11.3) — os 8 campos literais do wireframe."""
        return deps.documento_op(
            orchestration_id,
            lambda: svc.create_documento_comment(
                orchestration_id,
                tipo,
                autor=body.autor,
                tipo_comentario=body.tipo,
                severidade=body.severidade,
                descricao=body.descricao,
                trecho_relacionado=body.trecho_relacionado,
                acao_solicitada=body.acao_solicitada,
                actor=actor_de(request),
            ),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/documentos/comments/{comment_id}/resolve")
    def resolve_documento_comment(
        orchestration_id: str,
        comment_id: str,
        body: DocumentoCommentResolveBody,
        request: Request,
    ) -> Any:
        return deps.documento_op(
            orchestration_id,
            lambda: svc.resolve_documento_comment(
                orchestration_id,
                comment_id,
                resposta_do_autor=body.resposta_do_autor,
                actor=actor_de(request),
            ),
        )

    return router
