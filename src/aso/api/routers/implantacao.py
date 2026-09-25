"""Rotas de implantação: validações, deploy, encerramento, incidentes e bugs.

Extraídas do `create_app` monolítico no MEL-32 passo 10 (ADR-0066).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from aso.api.deps import ApiDeps, actor_de
from aso.api.schemas import (
    DeployApproveBody,
    DeployConfigBody,
    DeployPipelineBody,
    DeployRollbackBody,
    DeployRunBody,
    IncidentInvestigateBody,
    IncidentResolveBody,
    ValidationChecksBody,
)
from aso.control.models import Environment, ValidationCheck
from aso.execution.gate_validation import GateCommandError


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()
    svc = deps.svc

    @router.get("/v1/orchestrations/{orchestration_id}/validation-checks")
    def get_validation_checks(orchestration_id: str) -> Any:
        """Bateria efetiva de validações (fluxo §12, ADR-0022)."""
        deps.guard(orchestration_id)
        return svc.get_validation_checks(orchestration_id)

    @router.put("/v1/orchestrations/{orchestration_id}/validation-checks")
    def set_validation_checks(
        orchestration_id: str, body: ValidationChecksBody, request: Request
    ) -> Any:
        """Substitui a bateria — cada comando passa por `validate_gate_command`."""
        deps.guard(orchestration_id)
        try:
            return svc.set_validation_checks(
                orchestration_id,
                [ValidationCheck(**c.model_dump()) for c in body.checks],
                actor=actor_de(request),
            )
        except GateCommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.get("/v1/orchestrations/{orchestration_id}/validation-checks/suggest")
    def suggest_validation_checks(orchestration_id: str) -> Any:
        """Sugestão determinística por stack (ADR-0022) — não grava nada."""
        deps.guard(orchestration_id)
        return svc.suggest_validation_checks(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/deploy")
    def get_deploy(orchestration_id: str) -> Any:
        """Última implantação (fluxo §18-22 do fluxo.md, ADR-0023)."""
        deps.guard(orchestration_id)
        return svc.get_deploy(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/deploy/history")
    def get_deploy_history(orchestration_id: str) -> Any:
        """Histórico de tentativas de implantação — ring de até 5."""
        deps.guard(orchestration_id)
        return svc.get_deploy_history(orchestration_id)

    @router.put("/v1/orchestrations/{orchestration_id}/deploy/config")
    def set_deploy_config(orchestration_id: str, body: DeployConfigBody, request: Request) -> Any:
        """Configura comando/ambiente/health checks/rollback da implantação."""
        deps.guard(orchestration_id)
        try:
            return svc.set_deploy_config(
                orchestration_id,
                command=body.command,
                environment=body.environment,
                health_checks=(
                    [ValidationCheck(**c.model_dump()) for c in body.health_checks]
                    if body.health_checks is not None
                    else None
                ),
                rollback_command=body.rollback_command,
                actor=actor_de(request),
            )
        except GateCommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.get("/v1/orchestrations/{orchestration_id}/deploy/pipeline")
    def get_deploy_pipeline(orchestration_id: str) -> Any:
        """Status derivado por estágio (wf §19, §25, ADR-0029) — lista vazia =
        monoambiente legado, nenhum pipeline configurado."""
        deps.guard(orchestration_id)
        return svc.get_deploy_pipeline(orchestration_id)

    @router.put("/v1/orchestrations/{orchestration_id}/deploy/pipeline")
    def set_deploy_pipeline(
        orchestration_id: str, body: DeployPipelineBody, request: Request
    ) -> Any:
        """Configura o pipeline de estágios; lista vazia volta ao monoambiente
        legado (ADR-0023)."""
        deps.guard(orchestration_id)
        try:
            return svc.set_deploy_pipeline(
                orchestration_id,
                [
                    Environment(
                        chave=e.chave,
                        nome=e.nome,
                        ordem=e.ordem,
                        comando=e.comando,
                        health_checks=[ValidationCheck(**c.model_dump()) for c in e.health_checks],
                        rollback_command=e.rollback_command,
                        requer_aprovacao_humana=e.requer_aprovacao_humana,
                    )
                    for e in body.estagios
                ],
                actor=actor_de(request),
            )
        except GateCommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.post("/v1/orchestrations/{orchestration_id}/deploy/run")
    def run_deploy(orchestration_id: str, body: DeployRunBody, request: Request) -> Any:
        """Roda a implantação — exige comando configurado e o quality gate mais
        recente aprovado (fluxo §18); o resultado decide aceite automático ou humano.
        Com pipeline configurado, `body.estagio` escolhe qual estágio rodar
        (omitido, resolve o primeiro pendente — avanço governado, fluxo §19)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.run_deploy(
                orchestration_id,
                environment=body.environment,
                estagio=body.estagio,
                versao_app=body.versao_app,
                commit=body.commit,
                branch=body.branch,
                actor=actor_de(request),
            ),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/deploy/validate")
    def validate_deploy(orchestration_id: str, request: Request) -> Any:
        """Roda as verificações pós-implantação configuradas (fluxo §20)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.validate_deploy(orchestration_id, actor=actor_de(request)),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/deploy/approve")
    def approve_deploy(orchestration_id: str, body: DeployApproveBody, request: Request) -> Any:
        """Aceite final da implantação (fluxo §22) — ação crítica, exige admin."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.decide_deploy(
                orchestration_id,
                approved=body.approved,
                comentario=body.comentario,
                tipo_aceite=body.tipo_aceite,
                actor=actor_de(request),
            ),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/deploy/rollback")
    def rollback_deploy(orchestration_id: str, body: DeployRollbackBody, request: Request) -> Any:
        """Reverte a última implantação e abre uma tarefa de causa raiz (fluxo §21)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.rollback_deploy(
                orchestration_id,
                reason=body.reason,
                estrategia=body.estrategia,
                actor=actor_de(request),
            ),
        )

    # --- Telas 22/24/25/27 (aprovação, saúde, rollback, encerramento — ADR-0050) ---

    @router.get("/v1/orchestrations/{orchestration_id}/deploy/approval-checklist")
    def get_deploy_approval_checklist(orchestration_id: str) -> Any:
        """Checklist de 9 itens + avaliação de risco (Tela 22, wf §24)."""
        deps.guard(orchestration_id)
        return svc.get_deploy_approval_checklist(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/deploy/health")
    def get_deploy_health(orchestration_id: str) -> Any:
        """Saúde de 4 níveis + decisão sugerida (Tela 24, wf §26)."""
        return deps.card_op(orchestration_id, lambda: svc.get_deploy_health(orchestration_id))

    @router.get("/v1/orchestrations/{orchestration_id}/deploy/rollback-checklist")
    def get_rollback_checklist(orchestration_id: str) -> Any:
        """Checklist de 6 itens do rollback (Tela 25, wf §27)."""
        return deps.card_op(orchestration_id, lambda: svc.get_rollback_checklist(orchestration_id))

    @router.get("/v1/orchestrations/{orchestration_id}/closure")
    def get_demand_closure(orchestration_id: str) -> Any:
        """Relatório de encerramento da demanda, 13 blocos + métricas (Tela 27, wf §29)."""
        deps.guard(orchestration_id)
        return svc.get_demand_closure(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/closure/export")
    def export_demand_closure(orchestration_id: str) -> Any:
        """Markdown pronto para download (botão 'Exportar relatório', wf §29.2)."""
        deps.guard(orchestration_id)
        markdown = svc.export_demand_closure(orchestration_id)
        return Response(
            content=markdown,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="encerramento-{orchestration_id}.md"'
            },
        )

    # --- incidentes (wf §21, §27/§38, ADR-0032) ---

    @router.get("/v1/incidents")
    def list_all_incidents(
        status: str | None = Query(default=None),
        project_id: str | None = Query(default=None),
    ) -> Any:
        """Incidentes de todas as demandas (Tela "Incidentes" da sidebar, MEL-55/ADR-0078).

        Filtros vão para a consulta: nada de hidratar agregado para filtrar em memória (MEL-52)."""
        ids = {o.id for o in svc.list_all(project_id=project_id)} if project_id else None
        return svc.list_all_incidents(status=status, orchestration_ids=ids)

    @router.get("/v1/orchestrations/{orchestration_id}/incidents")
    def list_incidents(orchestration_id: str) -> Any:
        """Incidentes da orquestração — abertos automaticamente por rollback (fluxo §21)."""
        deps.guard(orchestration_id)
        return svc.list_incidents(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/incidents/{incident_id}")
    def get_incident(orchestration_id: str, incident_id: str) -> Any:
        deps.guard(orchestration_id)
        incident = svc.get_incident(orchestration_id, incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incidente inexistente")
        return incident

    @router.post("/v1/orchestrations/{orchestration_id}/incidents/{incident_id}/investigate")
    def investigate_incident(
        orchestration_id: str,
        incident_id: str,
        body: IncidentInvestigateBody,
        request: Request,
    ) -> Any:
        """Marca o incidente como em investigação."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.investigate_incident(
                orchestration_id, incident_id, detalhe=body.detalhe, actor=actor_de(request)
            ),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/incidents/{incident_id}/resolve")
    def resolve_incident(
        orchestration_id: str, incident_id: str, body: IncidentResolveBody, request: Request
    ) -> Any:
        """Resolve o incidente com a causa raiz identificada."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.resolve_incident(
                orchestration_id, incident_id, causa_raiz=body.causa_raiz, actor=actor_de(request)
            ),
        )

    # --- bugs manuais (Tela 21, wf §23, ADR-0049) ---

    @router.get("/v1/orchestrations/{orchestration_id}/bug-reports")
    def list_bug_reports(orchestration_id: str) -> Any:
        """Todos os bugs registrados manualmente na orquestração."""
        deps.guard(orchestration_id)
        return svc.list_bug_reports(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/bug-reports/{bug_report_id}")
    def get_bug_report(orchestration_id: str, bug_report_id: str) -> Any:
        deps.guard(orchestration_id)
        report = svc.get_bug_report(orchestration_id, bug_report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Registro de bug inexistente")
        return report

    return router
