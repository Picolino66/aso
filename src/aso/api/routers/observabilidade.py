"""Rotas de observabilidade: métricas, SLO, eventos (SSE), auditoria, runs e aprendizado.

Extraídas do `create_app` monolítico no MEL-32 passo 10 (ADR-0066).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from aso.api.deps import ApiDeps
from aso.governance.models import SloEvaluation
from aso.observability.aprendizado import recomendacoes_estruturadas


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()
    svc = deps.svc
    metrics = deps.metrics
    broker = deps.broker

    @router.get("/v1/orchestrations/{orchestration_id}/learning")
    def get_learning_report(orchestration_id: str) -> Any:
        """Relatório de aprendizado da demanda (§24) — retrabalho, falhas por
        etapa, desempenho por executor, intervenções humanas. Informativo."""
        deps.guard(orchestration_id)
        return svc.get_learning_report(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/learning/recommendations")
    def get_learning_recommendations(orchestration_id: str) -> Any:
        """8 recomendações estruturadas da Tela 29 (wf §31.3, ADR-0052) — 6 com
        justificativa quando disparadas, 2 permanentemente desabilitadas."""
        deps.guard(orchestration_id)
        return recomendacoes_estruturadas(svc.get_learning_report(orchestration_id))

    @router.get("/v1/learning")
    def get_learning_report_global(
        projeto: str | None = Query(default=None),
        data_de: str | None = Query(default=None),
        data_ate: str | None = Query(default=None),
    ) -> Any:
        """Mesmo relatório, consolidado entre orquestrações (§24) — recorte por
        projeto e período (Tela 29, wf §31, ADR-0052)."""
        return svc.get_learning_report_global(
            project_id=projeto, data_de=data_de, data_ate=data_ate
        )

    @router.get("/v1/learning/recommendations")
    def get_learning_recommendations_global(
        projeto: str | None = Query(default=None),
        data_de: str | None = Query(default=None),
        data_ate: str | None = Query(default=None),
    ) -> Any:
        """8 recomendações estruturadas cross-demanda (Tela 29, wf §31.3, ADR-0052)."""
        relatorio = svc.get_learning_report_global(
            project_id=projeto, data_de=data_de, data_ate=data_ate
        )
        return recomendacoes_estruturadas(relatorio)

    @router.get("/v1/orchestrations/{orchestration_id}/agent-log")
    def agent_log(
        orchestration_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=500, ge=1, le=2000),
    ) -> Any:
        """Saída ao vivo dos agentes desta orquestração; `after` é o cursor."""
        deps.guard(orchestration_id)
        return svc.agent_log(orchestration_id, after=after, limit=limit)

    # --- F7: observabilidade e feedback ---
    @router.get("/v1/metrics")
    def global_metrics() -> Any:
        return metrics.global_metrics()

    # --- Header (wf §2.3, ADR-0035) ---
    @router.get("/v1/header-summary")
    def header_summary(project_id: str | None = Query(default=None)) -> Any:
        """Execuções ativas, falhas e aprovações pendentes — escopadas ao
        `project_id` quando informado, senão globais."""
        return svc.header_summary(project_id=project_id)

    @router.get("/v1/search")
    def search(
        q: str = Query(default=""),
        project_id: str | None = Query(default=None),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> Any:
        """Busca global (wf §2.3, "Campo de busca"): demanda, card ou documento."""
        return svc.search(q, project_id=project_id, limit=limit)

    # --- Dashboard (wf §3.3, Tela 01, ADR-0037) ---
    @router.get("/v1/dashboard-summary")
    def dashboard_summary(project_id: str | None = Query(default=None)) -> Any:
        """Demandas ativas/em execução/bloqueadas/falhas, cards por status e
        aprovações pendentes por tipo — escopados ao `project_id` quando informado."""
        return svc.dashboard_summary(project_id=project_id)

    @router.get("/v1/activity")
    def recent_activity(limit: int = Query(default=20, ge=1, le=100)) -> Any:
        """Atividade recente global (tipo, ator, horário) — diferente da timeline
        por orquestração."""
        return svc.recent_activity(limit=limit)

    @router.get("/v1/audit")
    def audit_page(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
        projeto: str | None = Query(default=None),
        demanda: str | None = Query(default=None),
        agente: str | None = Query(default=None),
        etapa: str | None = Query(default=None),
        resultado: str | None = Query(default=None),
        data_de: str | None = Query(default=None),
        data_ate: str | None = Query(default=None),
    ) -> Any:
        """Auditoria cross-demanda com os 6 filtros do wf §30.3 (Tela 28, ADR-0051)."""
        return svc.audit_page(
            page=page,
            page_size=page_size,
            project_id=projeto,
            orchestration_id=demanda,
            agente=agente,
            etapa=etapa,
            resultado=resultado,
            data_de=data_de,
            data_ate=data_ate,
        )

    @router.get("/v1/audit/export")
    def export_audit(
        projeto: str | None = Query(default=None),
        demanda: str | None = Query(default=None),
        agente: str | None = Query(default=None),
        etapa: str | None = Query(default=None),
        resultado: str | None = Query(default=None),
        data_de: str | None = Query(default=None),
        data_ate: str | None = Query(default=None),
    ) -> Any:
        """CSV do resultado filtrado (wf §30.3, "Exportação")."""
        csv_text = svc.export_audit(
            project_id=projeto,
            orchestration_id=demanda,
            agente=agente,
            etapa=etapa,
            resultado=resultado,
            data_de=data_de,
            data_ate=data_ate,
        )
        return Response(
            content=csv_text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="auditoria.csv"'},
        )

    @router.get("/v1/orchestrations/{orchestration_id}/metrics")
    def orchestration_metrics(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return metrics.orchestration_metrics(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/slo")
    def slo_report(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return metrics.slo_report(orchestration_id)

    @router.post("/v1/orchestrations/{orchestration_id}/slo/evaluate", status_code=201)
    def slo_evaluate(orchestration_id: str) -> Any:
        """Avalia e persiste uma amostra de SLO (série temporal de burn-rate, F7)."""
        deps.guard(orchestration_id)
        report = metrics.slo_report(orchestration_id)
        eb = report["error_budget"]
        evaluation = SloEvaluation(
            orchestration_id=orchestration_id,
            fail_rate=eb["fail_rate"],
            burn_rate=eb["burn_rate"],
            consumed_pct=eb["consumed_pct"],
            severity=eb["severity"],
            breaches=report["breaches"],
            alerts_count=len(report["alerts"]),
        )
        return svc.record_slo_evaluation(orchestration_id, evaluation)

    @router.get("/v1/orchestrations/{orchestration_id}/slo-history")
    def slo_history(orchestration_id: str, limit: int | None = None) -> Any:
        """Série temporal de avaliações de SLO persistidas (as mais recentes)."""
        deps.guard(orchestration_id)
        return svc.list_slo_evaluations(orchestration_id, limit=limit)

    @router.get("/v1/orchestrations/{orchestration_id}/execution-metrics")
    def execution_metrics(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return metrics.execution_metrics(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/execution-timeline")
    def execution_timeline(orchestration_id: str) -> Any:
        """Timeline de custo por card (F7 avançado)."""
        deps.guard(orchestration_id)
        return metrics.execution_timeline(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/events/stream")
    async def events_stream(orchestration_id: str, request: Request) -> StreamingResponse:
        """SSE: emite um 'tick' a cada mutação da orquestração (console atualiza ao vivo)."""
        deps.guard(orchestration_id)
        queue = broker.subscribe(orchestration_id)

        async def gen() -> AsyncIterator[str]:
            try:
                yield f"data: {json.dumps({'tick': 0})}\n\n"
                while not await request.is_disconnected():
                    try:
                        seq = await asyncio.wait_for(queue.get(), timeout=1.0)
                        yield f"data: {json.dumps({'tick': seq})}\n\n"
                    except TimeoutError:
                        yield ": heartbeat\n\n"  # mantém a conexão viva
            finally:
                broker.unsubscribe(orchestration_id, queue)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @router.get("/v1/orchestrations/{orchestration_id}/runs")
    def list_agent_runs(orchestration_id: str, card_id: str | None = None) -> Any:
        """Registros de execução de agente da orquestração (ADR-0065)."""
        deps.guard(orchestration_id)
        return svc.list_agent_runs(orchestration_id, card_id=card_id)

    @router.get("/v1/runs/{run_id}")
    def get_agent_run(run_id: str) -> Any:
        try:
            return svc.get_agent_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.get("/v1/orchestrations/{orchestration_id}/audit")
    def audit(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.audit(orchestration_id)

    return router
