"""Rotas de orquestrações: criação, leitura, plano, configurações e ficha da demanda.

Extraídas do `create_app` monolítico no MEL-32 passo 10 (ADR-0066).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from aso.api.deps import ApiDeps, actor_de, exigir_admin_para_comando, raise_project_error
from aso.api.schemas import (
    AgentAssignmentBody,
    BudgetBody,
    ClassificationBody,
    CreateOrchestrationBody,
    ExecutionSettingsBody,
    FeedbackBody,
    PlanBody,
    RetriageBody,
)
from aso.control.project_service import (
    ProjectConflictError,
    ProjectNotFoundError,
    ProjectValidationError,
)
from aso.control.triage import DemandBrief
from aso.execution.gate_validation import GateCommandError
from aso.execution.workspace import WorkspaceService
from aso.shared.types import ExecutionMode


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()
    svc = deps.svc
    metrics = deps.metrics
    planning_client = deps.planning_client

    @router.post("/v1/orchestrations", status_code=201)
    def create_orchestration(body: CreateOrchestrationBody, request: Request) -> Any:
        exigir_admin_para_comando(request, body.validation_command)
        target_path: str | None = None
        if body.target_path and body.target_path.strip():
            try:
                target_path = str(WorkspaceService().validate(body.target_path))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        mode = body.execution_mode or ExecutionMode.FULL_PIPELINE
        if body.execution_mode == ExecutionMode.FULL_PIPELINE and planning_client is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Pipeline completo exige LLM de planejamento configurado; "
                    "escolha execução direta ou configure ASO_LLM_*."
                ),
            )
        if mode == ExecutionMode.CODE_EXECUTION and not (
            body.validation_command or os.environ.get("ASO_GATE_TEST_COMMAND")
        ):
            raise HTTPException(
                status_code=400, detail="Informe o comando de validação do workspace."
            )
        # Triagem (§1/§2 do fluxo.md) + criação passam por `create_with_triage`, o
        # único caminho correto (Ponto 1 herdado da avaliação do Incremento A: a
        # sequência estava duplicada só aqui, e outros pontos de entrada — a CLI —
        # nasciam sem ela). Nunca levanta por conta da triagem em si — TriageService
        # garante o fallback heurístico.
        #
        # Exceção deliberada (Tela 03, Cadastro completo, wf §5.2, ADR-0039): se o
        # corpo já traz uma `demand_brief` completa, o solicitante preencheu a
        # ficha à mão — rodar o agente de triagem por cima descartaria isso. Neste
        # caso vai direto a `create_orchestration`, sem re-triagem.
        try:
            if body.demand_brief is not None:
                # Bug real (code-review ultra): faltava `decision_input=` aqui — a
                # classificação preenchida à mão (tipo/complexidade/impactos/domínios)
                # nunca chegava ao planejador nem a `_apply_routing_rule`, que viam
                # um `DecisionInput` default (`domains=["backend"]`). `to_decision_input`
                # é a mesma tradução que `create_with_triage` já usa.
                brief = DemandBrief.model_validate(body.demand_brief)
                orch = svc.create_orchestration(
                    body.user_request,
                    project_id=body.project_id,
                    target_path=target_path,
                    execution_mode=mode,
                    executor=body.executor,
                    effort=body.effort,
                    validation_command=body.validation_command,
                    seed_cards=body.execution_mode != ExecutionMode.FULL_PIPELINE,
                    decision_input=brief.to_decision_input(body.user_request),
                    demand_brief=brief,
                    orcamento_usd=body.orcamento_usd,
                )
            else:
                orch = svc.create_with_triage(
                    body.user_request,
                    project_id=body.project_id,
                    target_path=target_path,
                    execution_mode=mode,
                    executor=body.executor,
                    effort=body.effort,
                    validation_command=body.validation_command,
                    seed_cards=body.execution_mode != ExecutionMode.FULL_PIPELINE,
                    orcamento_usd=body.orcamento_usd,
                )
        except (ProjectNotFoundError, ProjectValidationError, ProjectConflictError) as exc:
            raise_project_error(exc)
        except GateCommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        if body.execution_mode == ExecutionMode.FULL_PIPELINE and planning_client is not None:
            # Regra de negócio no IntakeService (MEL-32): o handler só traduz o aviso.
            aviso = svc.planejar_na_criacao(orch.id, planning_client, body.user_request)
            if aviso is not None:
                return JSONResponse(
                    status_code=201,
                    content={**svc.get(orch.id).model_dump(mode="json"), "aviso": aviso},
                )
        return orch

    @router.post("/v1/orchestrations/{orchestration_id}/plan", status_code=201)
    def plan_with_llm(orchestration_id: str, body: PlanBody) -> Any:
        """Planeja o produto com o LLM (M2) e materializa cards+ADRs no board."""
        deps.guard(orchestration_id)
        if planning_client is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "LLM não configurado: defina ASO_LLM_PROVIDER/ASO_LLM_API_KEY/ASO_LLM_MODEL."
                ),
            )
        return svc.planejar(orchestration_id, planning_client, body.idea)

    @router.get("/v1/orchestrations")
    def list_orchestrations(
        response: Response,
        page: int | None = Query(default=None, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
        project_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
        q: str | None = Query(default=None),
        executor: str | None = Query(default=None),
        created_from: str | None = Query(default=None),
        created_to: str | None = Query(default=None),
        tipo: str | None = Query(default=None),
        risco: str | None = Query(default=None),
        complexidade: str | None = Query(default=None),
        impacto: str | None = Query(default=None),
        aprovacao_humana: bool | None = Query(default=None),
    ) -> Any:
        """Tela 02 (Lista de demandas, wf §4.2, ADR-0038): 10 dos 11 filtros do
        wireframe (o 11º, "Prioridade", reaproveita `risco` — não existe
        prioridade de demanda como conceito próprio, só a de card, derivada do
        risco)."""
        filtros: dict[str, Any] = {
            "project_id": project_id,
            "status": status,
            "q": q,
            "executor": executor,
            "created_from": created_from,
            "created_to": created_to,
            "tipo": tipo,
            "risco": risco,
            "complexidade": complexidade,
            "impacto": impacto,
            "aprovacao_humana": aprovacao_humana,
        }
        if page is None:
            # Sem página pedida: devolve tudo que bate nos filtros (mesmo
            # contrato de sempre — `page` é o único gatilho de paginação).
            items = svc.list_all(**filtros)
            response.headers["X-Total-Count"] = str(len(items))
            return items
        result = svc.list_orchestrations_page(page=page, page_size=page_size, **filtros)
        response.headers["X-Total-Count"] = str(result["total"])
        return result["items"]

    @router.get("/v1/orchestrations/{orchestration_id}")
    def get_orchestration(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.get(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/context")
    def get_context(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.get_context(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/plan")
    def get_plan(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.get_plan(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/timeline")
    def get_timeline(
        orchestration_id: str,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
        newest_first: bool = Query(default=False),
    ) -> Any:
        deps.guard(orchestration_id)
        return svc.timeline_page(
            orchestration_id, page=page, page_size=page_size, newest_first=newest_first
        )

    @router.get("/v1/orchestrations/{orchestration_id}/next-step")
    def next_step(orchestration_id: str) -> Any:
        """O que falta para a esteira seguir: checklist, bloqueios e ação primária.

        Fonte única de verdade das regras que travam o avanço (ADR-0013) — a tela de
        detalhe apenas renderiza este contrato.
        """
        deps.guard(orchestration_id)
        breaches = metrics.slo_report(orchestration_id).get("breaches", [])
        return svc.next_step(orchestration_id, slo_breaches=list(breaches))

    @router.patch("/v1/orchestrations/{orchestration_id}/execution-settings")
    def update_execution_settings(
        orchestration_id: str, body: ExecutionSettingsBody, request: Request
    ) -> Any:
        deps.guard(orchestration_id)
        exigir_admin_para_comando(request, body.validation_command)
        try:
            return svc.update_execution_settings(
                orchestration_id,
                executor=body.executor,
                effort=body.effort,
                validation_command=body.validation_command,
                actor=actor_de(request),
            )
        except GateCommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.put("/v1/orchestrations/{orchestration_id}/budget")
    def set_budget(orchestration_id: str, body: BudgetBody, request: Request) -> Any:
        """Eleva/remove o teto de orçamento (§1.2/§3.2, ADR-0026) — ação crítica,
        exige admin (`/budget` no sufixo administrativo de `api/auth.py`)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.set_orcamento(orchestration_id, body.teto_usd, actor=actor_de(request)),
        )

    @router.get("/v1/orchestrations/{orchestration_id}/worktrees")
    def list_worktrees(orchestration_id: str) -> Any:
        """Worktrees em disco desta orquestração, com `orfao` marcado (§3.3, ADR-0027)."""
        deps.guard(orchestration_id)
        return svc.list_worktrees(orchestration_id)

    @router.post("/v1/orchestrations/{orchestration_id}/worktrees/prune")
    def prune_worktrees(orchestration_id: str, request: Request) -> Any:
        """Remove os worktrees órfãos (não referenciados por card ativo) — nunca
        `rm -rf`, exige admin: pode destruir trabalho de agente não mesclado."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.prune_worktrees(orchestration_id, actor=actor_de(request)),
        )

    @router.put("/v1/orchestrations/{orchestration_id}/agents/{key}")
    def set_agent_assignment(
        orchestration_id: str, key: str, body: AgentAssignmentBody, request: Request
    ) -> Any:
        """Define o executor de uma etapa (F1..F7) ou do nomeador de branches/commits."""
        deps.guard(orchestration_id)
        try:
            return svc.set_agent_assignment(
                orchestration_id,
                key,
                executor=body.executor,
                effort=body.effort,
                actor=actor_de(request),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.delete("/v1/orchestrations/{orchestration_id}/agents/{key}")
    def clear_agent_assignment(orchestration_id: str, key: str, request: Request) -> Any:
        """Remove o executor da etapa: ela volta a herdar o padrão da orquestração."""
        deps.guard(orchestration_id)
        try:
            return svc.clear_agent_assignment(orchestration_id, key, actor=actor_de(request))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.get("/v1/orchestrations/{orchestration_id}/brief")
    def get_brief(orchestration_id: str) -> Any:
        """Ficha estruturada da demanda (§1/§2 do fluxo.md)."""
        deps.guard(orchestration_id)
        return svc.get_demand_brief(orchestration_id)

    @router.post("/v1/orchestrations/{orchestration_id}/brief")
    def retriage_brief(orchestration_id: str, body: RetriageBody, request: Request) -> Any:
        """Re-tria a demanda — útil depois que o operador responde `perguntas_abertas`."""
        deps.guard(orchestration_id)
        return svc.retriage_demand(
            orchestration_id, executor=body.executor, effort=body.effort, actor=actor_de(request)
        )

    @router.patch("/v1/orchestrations/{orchestration_id}/classification")
    def update_classification(
        orchestration_id: str, body: ClassificationBody, request: Request
    ) -> Any:
        """Edição pontual da classificação, com auditoria antes/depois (Tela 05,
        wf §7, ADR-0044)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.update_classification(
                orchestration_id,
                tipo=body.tipo,
                risco=body.risco,
                complexidade=body.complexidade,
                impactos=body.impactos,
                dominios=body.dominios,
                actor=actor_de(request),
            ),
        )

    @router.get("/v1/orchestrations/{orchestration_id}/recommendation")
    def get_recommendation(orchestration_id: str) -> Any:
        """Painel de recomendação (Tela 13, wf §15, ADR-0044) — o que o motor
        decidiria hoje para esta demanda; não persiste nada."""
        deps.guard(orchestration_id)
        return svc.preview_recommendation(orchestration_id)

    @router.post("/v1/orchestrations/{orchestration_id}/feedback", status_code=201)
    def add_feedback(orchestration_id: str, body: FeedbackBody) -> Any:
        deps.guard(orchestration_id)
        return svc.add_feedback(orchestration_id, body.text, card_type=body.card_type)

    @router.post("/v1/orchestrations/{orchestration_id}/duplicate", status_code=201)
    def duplicate_orchestration(orchestration_id: str, request: Request) -> Any:
        """Duplicar (Tela 02, wf §4.4, ADR-0038): nova orquestração a partir do
        `user_request`/projeto/execução da origem, re-triada do zero."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.duplicate_orchestration(orchestration_id, actor=actor_de(request)),
        )

    return router
