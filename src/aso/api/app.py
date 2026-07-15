"""API v1 do ASO Runtime (FastAPI, TASK-13).

Adapter fino sobre o OrchestrationService. Contrato em contracts/openapi.yaml.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, NoReturn

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from structlog.contextvars import bind_contextvars, clear_contextvars

from aso.api.auth import AuthService, required_role
from aso.bootstrap import build_candidate_providers, build_service
from aso.control.orchestration_service import OrchestrationService
from aso.control.planning import PlanningService
from aso.control.project_service import (
    ProjectConflictError,
    ProjectNotFoundError,
    ProjectValidationError,
)
from aso.execution.codex_discovery import CodexDiscoveryError
from aso.execution.gate_validation import GateCommandError
from aso.execution.llm_client import LlmClient, build_llm_client_from_env
from aso.execution.workspace import WorkspaceError, WorkspaceService
from aso.governance.models import ContextPatch, SloEvaluation
from aso.observability.broker import EventBroker
from aso.observability.logging import get_logger
from aso.observability.metrics import MetricsService
from aso.observability.ratelimit import RateLimiter
from aso.observability.tracing import get_tracer
from aso.shared.ids import gen_id
from aso.shared.types import ExecutionMode, PatchType, Phase

_STATIC_DIR = Path(__file__).resolve().parent / "static"


class CreateOrchestrationBody(BaseModel):
    user_request: str
    project_id: str | None = None
    # Pasta de trabalho (workspace) desta orquestração; validada/normalizada no create.
    target_path: str | None = None
    execution_mode: ExecutionMode | None = None
    executor: str | None = None
    effort: str | None = None
    validation_command: str | None = None


class AnalyzeFolderBody(BaseModel):
    executor: str | None = None
    effort: str | None = None


class ExecutionSettingsBody(BaseModel):
    executor: str | None = None
    effort: str | None = None
    validation_command: str | None = None


class CreateProjectBody(BaseModel):
    name: str
    description: str = ""
    target_path: str


class UpdateProjectBody(BaseModel):
    name: str | None = None
    description: str | None = None
    target_path: str | None = None


class RestoreProjectBody(BaseModel):
    target_path: str | None = None


class PlanBody(BaseModel):
    idea: str


class RunGateBody(BaseModel):
    phase: Phase | None = None


class RunPhaseBody(BaseModel):
    phase: Phase | None = None
    executor: str | None = None
    effort: str | None = None


class AutopilotBody(BaseModel):
    executor: str | None = None
    effort: str | None = None


class ExecutorBody(BaseModel):
    name: str
    kind: str = "cli"  # mock | llm | cli
    provider: str = ""
    model: str = ""
    effort: str = "medium"
    command: str = ""
    base_url: str = ""
    api_key_env: str = ""
    is_default: bool = False


class FeedbackBody(BaseModel):
    text: str
    card_type: str = "Improvement"


class RollbackBody(BaseModel):
    to_snapshot: str


class RestoreSectionBody(BaseModel):
    section: str


class ApprovalBody(BaseModel):
    action: str
    risk: str = "medium"
    reason: str = ""


class AssignAgentBody(BaseModel):
    agent: str


class MoveBody(BaseModel):
    to_column: str


class BlockBody(BaseModel):
    reason: str = ""


class OpenPrBody(BaseModel):
    branch: str | None = None
    title: str = ""


class StatusBody(BaseModel):
    status: str


class ContextPatchBody(BaseModel):
    agent: str
    phase: Phase
    patch_type: PatchType
    target_path: str
    content: Any = None
    requires_adr: bool = False
    requires_approval: bool = False
    linked_adrs: list[str] = []
    card_id: str | None = None


def create_app(
    service: OrchestrationService | None = None,
    auth: AuthService | None = None,
    *,
    llm_client: LlmClient | None = None,
) -> FastAPI:
    """Cria a aplicação FastAPI, opcionalmente com service/auth/llm injetados."""
    svc = service or OrchestrationService()
    auth = auth or AuthService.from_env()
    # Cérebro do autopilot: cliente LLM injetado (testes) ou montado do ambiente.
    planning_client = llm_client or build_llm_client_from_env()
    metrics = MetricsService(svc)
    log = get_logger()
    tracer = get_tracer()
    limiter = RateLimiter.from_env()
    broker = EventBroker()
    app = FastAPI(
        title="ASO Runtime API",
        version="1.0.0",
        description=(
            "Runtime multiagente de engenharia de software com Kanban, governança de "
            "contexto (ContextBus), ADRs, quality gates e snapshots. Docs interativas em /docs."
        ),
    )

    _PUBLIC = ("/health", "/docs", "/redoc", "/openapi.json", "/ui", "/metrics")
    # Paths de infraestrutura (healthcheck/scrape) — não logamos para não afogar o stdout.
    _QUIET_PATHS = ("/health", "/metrics")

    @app.middleware("http")
    async def gateway(request: Request, call_next: Any) -> Any:
        """Correlation-id + rate-limit + RBAC + tracing + log estruturado."""
        request_id = request.headers.get("x-request-id") or gen_id("req")
        clear_contextvars()
        bind_contextvars(request_id=request_id)
        path = request.url.path
        client = request.client.host if request.client else "anon"

        def _resp(resp: Any) -> Any:
            resp.headers["X-Request-ID"] = request_id
            return resp

        if not limiter.allow(client):
            return _resp(JSONResponse(status_code=429, content={"detail": "Rate limit excedido"}))

        actor = "-"
        if not (path == "/" or path.startswith(_PUBLIC)):
            # EventSource não envia headers; aceita token via query param `?token=`.
            authz = request.headers.get("authorization")
            if authz is None and request.query_params.get("token"):
                authz = f"Bearer {request.query_params['token']}"
            principal = auth.authenticate(authz)
            if principal is None:
                return _resp(
                    JSONResponse(status_code=401, content={"detail": "Token ausente ou inválido"})
                )
            if not principal.can(required_role(request.method, path)):
                return _resp(
                    JSONResponse(status_code=403, content={"detail": "Permissão insuficiente"})
                )
            request.state.principal = principal
            actor = principal.actor
        bind_contextvars(actor=actor)

        start = time.perf_counter()
        with tracer.start_as_current_span("http.request") as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.route", path)
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
        # Notifica o console (SSE) após mutação bem-sucedida numa orquestração.
        parts = path.split("/")
        if (
            request.method != "GET"
            and response.status_code < 400
            and len(parts) >= 4
            and parts[1] == "v1"
            and parts[2] == "orchestrations"
        ):
            broker.publish(parts[3])
        if path not in _QUIET_PATHS:  # não loga ruído de healthcheck/scrape
            log.info(
                "request",
                method=request.method,
                path=path,
                status=response.status_code,
                ms=round((time.perf_counter() - start) * 1000, 1),
                actor=actor,
            )
        return _resp(response)

    @app.get("/health")
    def health() -> Any:
        return {"status": "ok"}

    @app.get("/metrics")
    def prometheus_metrics() -> Response:
        return Response(content=metrics.prometheus(), media_type="text/plain; version=0.0.4")

    @app.get("/")
    def root() -> Any:
        return {
            "name": "ASO Runtime",
            "version": "1.0.0",
            "ui": "/ui/",
            "docs": "/docs",
            "redoc": "/redoc",
            "openapi": "/openapi.json",
        }

    def _guard(orchestration_id: str) -> None:
        try:
            svc.get(orchestration_id)
        except KeyError as exc:  # noqa: F841
            raise HTTPException(status_code=404, detail="Orquestração inexistente") from None

    @app.get("/v1/fs/dirs")
    def list_dirs(path: str | None = Query(default=None)) -> Any:
        """Lista subdiretórios (navegador de pastas da UI). Só nomes/paths de pastas."""
        try:
            return WorkspaceService().list_dirs(path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    def _actor(request: Request) -> str:
        return str(request.state.principal.actor)

    def _raise_project_error(exc: Exception) -> NoReturn:
        if isinstance(exc, ProjectNotFoundError):
            raise HTTPException(status_code=404, detail=str(exc)) from None
        if isinstance(exc, ProjectValidationError):
            raise HTTPException(status_code=400, detail=str(exc)) from None
        raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.get("/v1/fs/analyze/stream")
    def stream_workspace_analysis(path: str = Query(...)) -> StreamingResponse:
        """Emite o progresso da pré-análise somente leitura de uma pasta.

        A lista é materializada antes de iniciar o SSE para conhecer o total e para
        devolver erros de caminho/permissão como HTTP normal, antes dos headers do
        streaming. A enumeração em si não toca git, docs nem o ContextBus.
        """
        workspace = WorkspaceService()
        try:
            root = workspace.validate(path)
            files = list(workspace.iter_files(root))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

        def events() -> Iterator[str]:
            total = len(files)

            def event(current: int, file: Path | None) -> str:
                payload = {
                    "percent": 100 if total == 0 else round(current * 100 / total),
                    "current": current,
                    "total": total,
                    "file": str(file.relative_to(root)) if file is not None else None,
                }
                return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            yield event(0, None)
            for current, file in enumerate(files, start=1):
                yield event(current, file)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/v1/orchestrations", status_code=201)
    def create_orchestration(body: CreateOrchestrationBody) -> Any:
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
        try:
            orch = svc.create_orchestration(
                body.user_request,
                project_id=body.project_id,
                target_path=target_path,
                execution_mode=mode,
                executor=body.executor,
                effort=body.effort,
                validation_command=body.validation_command,
                seed_cards=body.execution_mode != ExecutionMode.FULL_PIPELINE,
            )
        except (ProjectNotFoundError, ProjectValidationError, ProjectConflictError) as exc:
            _raise_project_error(exc)
        except GateCommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        if body.execution_mode == ExecutionMode.FULL_PIPELINE and planning_client is not None:
            plan = PlanningService(planning_client).plan(body.user_request)
            svc.populate_from_plan(orch.id, plan)
        return orch

    @app.post("/v1/orchestrations/{orchestration_id}/plan", status_code=201)
    def plan_with_llm(orchestration_id: str, body: PlanBody) -> Any:
        """Planeja o produto com o LLM (M2) e materializa cards+ADRs no board."""
        _guard(orchestration_id)
        if planning_client is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "LLM não configurado: defina ASO_LLM_PROVIDER/ASO_LLM_API_KEY/ASO_LLM_MODEL."
                ),
            )
        plan = PlanningService(planning_client).plan(body.idea)
        return svc.populate_from_plan(orchestration_id, plan)

    @app.get("/v1/orchestrations")
    def list_orchestrations(
        response: Response,
        page: int | None = Query(default=None, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
        project_id: str | None = Query(default=None),
    ) -> Any:
        if page is None:
            items = svc.list_all(project_id=project_id)
            response.headers["X-Total-Count"] = str(len(items))
            return items
        result = svc.list_orchestrations_page(page=page, page_size=page_size, project_id=project_id)
        response.headers["X-Total-Count"] = str(result["total"])
        return result["items"]

    @app.get("/v1/orchestrations/{orchestration_id}")
    def get_orchestration(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return svc.get(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/context")
    def get_context(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return svc.get_context(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/plan")
    def get_plan(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return svc.get_plan(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/timeline")
    def get_timeline(
        orchestration_id: str,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
    ) -> Any:
        _guard(orchestration_id)
        return svc.timeline_page(orchestration_id, page=page, page_size=page_size)

    @app.get("/v1/orchestrations/{orchestration_id}/cards")
    def get_cards(
        orchestration_id: str,
        status: str | None = None,
        card_type: str | None = Query(default=None, alias="type"),
        assignee: str | None = None,
    ) -> Any:
        _guard(orchestration_id)
        if status or card_type or assignee:
            return svc.filter_cards(
                orchestration_id, status=status, card_type=card_type, assignee=assignee
            )
        return svc.get_cards(orchestration_id)

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/run")
    def run_card(orchestration_id: str, card_id: str) -> Any:
        _guard(orchestration_id)
        try:
            return svc.run_card(orchestration_id, card_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/v1/orchestrations/{orchestration_id}/quality-gates/run")
    def run_gate(orchestration_id: str, body: RunGateBody) -> Any:
        _guard(orchestration_id)
        return svc.run_quality_gate(orchestration_id, body.phase)

    @app.post("/v1/orchestrations/{orchestration_id}/run-plan")
    def run_plan(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        try:
            return svc.run_plan(orchestration_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.get("/v1/executors")
    def list_executors() -> Any:
        """Executores disponíveis para escolha por etapa (nome, tipo, modelo, esforços)."""
        return svc.list_executors()

    @app.post("/v1/executors", status_code=201)
    def upsert_executor(body: ExecutorBody) -> Any:
        """Cria/atualiza um perfil de executor (tela de configurações). Chave fica no env."""
        from aso.execution.catalog import ExecutorProfile

        return svc.save_executor(ExecutorProfile(**body.model_dump()))

    @app.post("/v1/executors/sync")
    def sync_executors() -> Any:
        """Sincroniza os modelos anunciados pelo Codex efetivo do processo da API."""
        try:
            return svc.sync_codex_executors()
        except CodexDiscoveryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.delete("/v1/executors/{name}")
    def delete_executor(name: str) -> Any:
        """Remove um perfil de executor (exceto 'mock')."""
        try:
            return svc.delete_executor(name)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    # ---- Projetos (agrupadores do Kanban Macro) ------------------------------

    @app.get("/v1/projects")
    def list_projects(include_archived: bool = Query(default=False)) -> Any:
        return svc.list_projects(include_archived=include_archived)

    @app.post("/v1/projects", status_code=201)
    def create_project(body: CreateProjectBody, request: Request) -> Any:
        try:
            return svc.create_project(
                name=body.name,
                description=body.description,
                target_path=body.target_path,
                actor=_actor(request),
            )
        except (ProjectValidationError, ProjectConflictError) as exc:
            _raise_project_error(exc)

    @app.get("/v1/projects/{project_id}")
    def get_project(project_id: str) -> Any:
        try:
            return svc.get_project(project_id)
        except ProjectNotFoundError as exc:
            _raise_project_error(exc)

    @app.patch("/v1/projects/{project_id}")
    @app.put("/v1/projects/{project_id}")
    def update_project(project_id: str, body: UpdateProjectBody, request: Request) -> Any:
        try:
            return svc.update_project(
                project_id,
                name=body.name,
                description=body.description,
                target_path=body.target_path,
                actor=_actor(request),
            )
        except (ProjectNotFoundError, ProjectValidationError, ProjectConflictError) as exc:
            _raise_project_error(exc)

    @app.delete("/v1/projects/{project_id}", status_code=200)
    def archive_project(project_id: str, request: Request) -> Any:
        """Arquiva metadados sem apagar orquestrações nem rastreabilidade."""
        try:
            return svc.archive_project(project_id, actor=_actor(request))
        except ProjectNotFoundError as exc:
            _raise_project_error(exc)

    @app.post("/v1/projects/{project_id}/restore")
    def restore_project(project_id: str, body: RestoreProjectBody, request: Request) -> Any:
        try:
            return svc.restore_project(
                project_id, actor=_actor(request), target_path=body.target_path
            )
        except (ProjectNotFoundError, ProjectValidationError, ProjectConflictError) as exc:
            _raise_project_error(exc)

    @app.get("/v1/projects/{project_id}/events")
    def project_events(project_id: str) -> Any:
        try:
            return svc.project_events(project_id)
        except ProjectNotFoundError as exc:
            _raise_project_error(exc)

    @app.post("/v1/orchestrations/{orchestration_id}/run-phase")
    def run_phase(orchestration_id: str, body: RunPhaseBody) -> Any:
        """Executa uma fase ponta a ponta e abre a aprovação de avanço (autopilot M3)."""
        _guard(orchestration_id)
        try:
            return svc.run_phase(
                orchestration_id, body.phase, executor=body.executor, effort=body.effort
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/v1/orchestrations/{orchestration_id}/analyze-folder", status_code=201)
    def analyze_folder(orchestration_id: str, body: AnalyzeFolderBody | None = None) -> Any:
        """Analisa a pasta da orquestração e gera/atualiza a documentação docs-first."""
        _guard(orchestration_id)
        body = body or AnalyzeFolderBody()
        try:
            return svc.analyze_folder(orchestration_id, executor=body.executor, effort=body.effort)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except (ValueError, WorkspaceError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.patch("/v1/orchestrations/{orchestration_id}/execution-settings")
    def update_execution_settings(
        orchestration_id: str, body: ExecutionSettingsBody, request: Request
    ) -> Any:
        _guard(orchestration_id)
        try:
            return svc.update_execution_settings(
                orchestration_id,
                executor=body.executor,
                effort=body.effort,
                validation_command=body.validation_command,
                actor=_actor(request),
            )
        except GateCommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/v1/orchestrations/{orchestration_id}/advance-phase")
    def advance_phase(orchestration_id: str) -> Any:
        """Avança para a próxima fase (governado)."""
        _guard(orchestration_id)
        try:
            return svc.advance_phase(orchestration_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/v1/orchestrations/{orchestration_id}/recover-execution")
    def recover_invalid_execution(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        try:
            return svc.recover_invalid_execution(orchestration_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/v1/orchestrations/{orchestration_id}/autopilot")
    def start_autopilot(orchestration_id: str, body: AutopilotBody | None = None) -> Any:
        """Dá partida no autopilot (M4): roda a fase atual; aprovar avança sozinho."""
        _guard(orchestration_id)
        body = body or AutopilotBody()
        try:
            return svc.start_autopilot(orchestration_id, executor=body.executor, effort=body.effort)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.get("/v1/orchestrations/{orchestration_id}/cards/stats")
    def cards_stats(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return svc.count_cards_by_status(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/cards/by-status/{status}")
    def cards_by_status(orchestration_id: str, status: str) -> Any:
        _guard(orchestration_id)
        return svc.cards_by_status(orchestration_id, status)

    @app.get("/v1/orchestrations/{orchestration_id}/adrs")
    def list_adrs(
        orchestration_id: str,
        status: str | None = None,
        q: str | None = None,
    ) -> Any:
        _guard(orchestration_id)
        if status or q:
            return svc.search_adrs(orchestration_id, status=status, query=q)
        return svc.list_adrs(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/adrs/by-status/{status}")
    def adrs_by_status(orchestration_id: str, status: str) -> Any:
        _guard(orchestration_id)
        return svc.adrs_by_status(orchestration_id, status)

    @app.get("/v1/orchestrations/{orchestration_id}/adrs/{adr_id}/linked-cards")
    def adr_linked_cards(orchestration_id: str, adr_id: str) -> Any:
        _guard(orchestration_id)
        return svc.cards_linked_to_adr(orchestration_id, adr_id)

    @app.get("/v1/orchestrations/{orchestration_id}/snapshots")
    def list_snapshots(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return svc.list_snapshots(orchestration_id)

    # --- F7: observabilidade e feedback ---
    @app.get("/v1/metrics")
    def global_metrics() -> Any:
        return metrics.global_metrics()

    @app.get("/v1/orchestrations/{orchestration_id}/metrics")
    def orchestration_metrics(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return metrics.orchestration_metrics(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/slo")
    def slo_report(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return metrics.slo_report(orchestration_id)

    @app.post("/v1/orchestrations/{orchestration_id}/slo/evaluate", status_code=201)
    def slo_evaluate(orchestration_id: str) -> Any:
        """Avalia e persiste uma amostra de SLO (série temporal de burn-rate, F7)."""
        _guard(orchestration_id)
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

    @app.get("/v1/orchestrations/{orchestration_id}/slo-history")
    def slo_history(orchestration_id: str, limit: int | None = None) -> Any:
        """Série temporal de avaliações de SLO persistidas (as mais recentes)."""
        _guard(orchestration_id)
        return svc.list_slo_evaluations(orchestration_id, limit=limit)

    @app.get("/v1/orchestrations/{orchestration_id}/execution-metrics")
    def execution_metrics(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return metrics.execution_metrics(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/execution-timeline")
    def execution_timeline(orchestration_id: str) -> Any:
        """Timeline de custo por card (F7 avançado)."""
        _guard(orchestration_id)
        return metrics.execution_timeline(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/events/stream")
    async def events_stream(orchestration_id: str, request: Request) -> StreamingResponse:
        """SSE: emite um 'tick' a cada mutação da orquestração (console atualiza ao vivo)."""
        _guard(orchestration_id)
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

    @app.post("/v1/orchestrations/{orchestration_id}/feedback", status_code=201)
    def add_feedback(orchestration_id: str, body: FeedbackBody) -> Any:
        _guard(orchestration_id)
        return svc.add_feedback(orchestration_id, body.text, card_type=body.card_type)

    # --- gates, conflitos e ciclo de vida (§28) ---
    @app.get("/v1/orchestrations/{orchestration_id}/quality-gates")
    def list_gates(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return svc.list_gate_results(orchestration_id)

    @app.get("/v1/quality-gates/{gate_id}")
    def get_gate(gate_id: str) -> Any:
        gate = svc.find_gate_result(gate_id)
        if gate is None:
            raise HTTPException(status_code=404, detail="Quality gate inexistente")
        return gate

    @app.get("/v1/orchestrations/{orchestration_id}/conflicts")
    def list_conflicts(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return svc.conflicts(orchestration_id)

    @app.post("/v1/orchestrations/{orchestration_id}/conflicts/{conflict_id}/resolve")
    def resolve_conflict(orchestration_id: str, conflict_id: str) -> Any:
        _guard(orchestration_id)
        try:
            return svc.resolve_conflict(orchestration_id, conflict_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    # --- Pull Requests (§26, MVP-4) ---
    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/open-pr", status_code=201)
    def open_pr(orchestration_id: str, card_id: str, body: OpenPrBody) -> Any:
        return _card_op(
            orchestration_id,
            lambda: svc.open_pr(orchestration_id, card_id, branch=body.branch, title=body.title),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/race")
    def race_card(orchestration_id: str, card_id: str) -> Any:
        """Roda os agentes CLI candidatos (§26A.6) em paralelo e compara os diffs."""
        _guard(orchestration_id)
        # Candidatos rodam na pasta (workspace) desta orquestração, se definida.
        providers = build_candidate_providers(svc.get(orchestration_id).target_path)
        if not providers:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Nenhum candidato configurado: defina ASO_CANDIDATE_COMMANDS e a pasta "
                    "da orquestração (ou ASO_TARGET_REPO)."
                ),
            )
        return _card_op(
            orchestration_id, lambda: svc.race_card(orchestration_id, card_id, providers)
        )

    @app.get("/v1/orchestrations/{orchestration_id}/candidate-runs")
    def list_candidate_runs(orchestration_id: str, card_id: str | None = None) -> Any:
        """Histórico rastreável de corridas de candidatos (§26A.6)."""
        _guard(orchestration_id)
        return svc.list_candidate_runs(orchestration_id, card_id)

    @app.get("/v1/orchestrations/{orchestration_id}/pulls")
    def list_pulls(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return svc.list_pulls(orchestration_id)

    @app.post("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/ci")
    def report_ci(orchestration_id: str, pr_id: str, body: StatusBody) -> Any:
        return _card_op(
            orchestration_id, lambda: svc.report_ci(orchestration_id, pr_id, body.status)
        )

    @app.post("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/ci/run")
    def run_pr_ci(orchestration_id: str, pr_id: str) -> Any:
        return _card_op(orchestration_id, lambda: svc.run_pr_ci(orchestration_id, pr_id))

    @app.post("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/review")
    def report_review(orchestration_id: str, pr_id: str, body: StatusBody) -> Any:
        return _card_op(
            orchestration_id, lambda: svc.report_review(orchestration_id, pr_id, body.status)
        )

    @app.post("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/merge")
    def merge_pr(orchestration_id: str, pr_id: str) -> Any:
        _guard(orchestration_id)
        try:
            return svc.merge_pr(orchestration_id, pr_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/v1/orchestrations/{orchestration_id}/rollback", status_code=202)
    def rollback(orchestration_id: str, body: RollbackBody) -> Any:
        _guard(orchestration_id)
        try:
            return svc.rollback(orchestration_id, body.to_snapshot)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @app.get("/v1/orchestrations/{orchestration_id}/snapshots/{version}/restore-section/preview")
    def preview_restore_section(orchestration_id: str, version: str, section: str) -> Any:
        """Dry-run: mostra o impacto da restauração seletiva sem aplicar (§23)."""
        _guard(orchestration_id)
        try:
            return svc.preview_restore_section(orchestration_id, version, section)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @app.post(
        "/v1/orchestrations/{orchestration_id}/snapshots/{version}/restore-section",
        status_code=202,
    )
    def restore_section(orchestration_id: str, version: str, body: RestoreSectionBody) -> Any:
        """Restauração seletiva de uma seção a partir de um snapshot (§23; admin)."""
        _guard(orchestration_id)
        try:
            return svc.restore_section(orchestration_id, version, body.section)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @app.post("/v1/orchestrations/{orchestration_id}/cancel")
    def cancel(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return svc.cancel(orchestration_id)

    @app.post("/v1/orchestrations/{orchestration_id}/resume")
    def resume(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return svc.resume(orchestration_id)

    @app.post("/v1/orchestrations/{orchestration_id}/retry")
    def retry(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return {"retried": svc.retry(orchestration_id)}

    @app.get("/v1/orchestrations/{orchestration_id}/snapshots/{from_v}/diff/{to_v}")
    def snapshot_diff(orchestration_id: str, from_v: str, to_v: str) -> Any:
        _guard(orchestration_id)
        try:
            return svc.snapshot_diff(orchestration_id, from_v, to_v)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    def _card_op(orchestration_id: str, fn: Any) -> Any:
        _guard(orchestration_id)
        try:
            return fn()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/assign-agent")
    def assign_agent(orchestration_id: str, card_id: str, body: AssignAgentBody) -> Any:
        return _card_op(
            orchestration_id, lambda: svc.assign_agent(orchestration_id, card_id, body.agent)
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/move")
    def move_card(orchestration_id: str, card_id: str, body: MoveBody) -> Any:
        return _card_op(
            orchestration_id, lambda: svc.move_card(orchestration_id, card_id, body.to_column)
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/block")
    def block_card(orchestration_id: str, card_id: str, body: BlockBody) -> Any:
        return _card_op(
            orchestration_id, lambda: svc.block_card(orchestration_id, card_id, body.reason)
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/unblock")
    def unblock_card(orchestration_id: str, card_id: str) -> Any:
        return _card_op(orchestration_id, lambda: svc.unblock_card(orchestration_id, card_id))

    # --- approvals (§28.7) ---
    @app.post("/v1/orchestrations/{orchestration_id}/approvals", status_code=201)
    def create_approval(orchestration_id: str, body: ApprovalBody) -> Any:
        _guard(orchestration_id)
        return svc.request_approval(
            orchestration_id, body.action, risk=body.risk, reason=body.reason
        )

    @app.get("/v1/orchestrations/{orchestration_id}/approvals")
    def list_orch_approvals(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return svc.list_approvals(orchestration_id)

    @app.get("/v1/approvals")
    def list_approvals() -> Any:
        return svc.list_all_approvals()

    @app.get("/v1/approvals/{approval_id}")
    def get_approval(approval_id: str) -> Any:
        approval = svc.get_approval(approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="Aprovação inexistente")
        return approval

    @app.post("/v1/approvals/{approval_id}/approve")
    def approve(approval_id: str, request: Request) -> Any:
        try:
            return svc.decide_approval(
                approval_id, approved=True, approved_by=request.state.principal.actor
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @app.post("/v1/approvals/{approval_id}/reject")
    def reject(approval_id: str, request: Request) -> Any:
        try:
            return svc.decide_approval(
                approval_id, approved=False, approved_by=request.state.principal.actor
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    # --- context patches e auditoria (§18, §33) ---
    @app.get("/v1/orchestrations/{orchestration_id}/patches")
    def list_patches(orchestration_id: str, status: str | None = None) -> Any:
        _guard(orchestration_id)
        return svc.list_patches(orchestration_id, status=status)

    @app.get("/v1/orchestrations/{orchestration_id}/patches/{patch_id}")
    def get_patch(orchestration_id: str, patch_id: str) -> Any:
        _guard(orchestration_id)
        patch = svc.get_patch(orchestration_id, patch_id)
        if patch is None:
            raise HTTPException(status_code=404, detail="Patch inexistente")
        return patch

    @app.post("/v1/orchestrations/{orchestration_id}/context-patches")
    def submit_patch(orchestration_id: str, body: ContextPatchBody) -> Any:
        _guard(orchestration_id)
        patch = ContextPatch(
            orchestration_id=orchestration_id,
            card_id=body.card_id,
            agent=body.agent,
            phase=body.phase,
            patch_type=body.patch_type,
            target_path=body.target_path,
            content=body.content,
            requires_adr=body.requires_adr,
            requires_approval=body.requires_approval,
            linked_adrs=body.linked_adrs,
        )
        result = svc.submit_patch(orchestration_id, patch)
        return {"status": result.status.value, "version": result.version, "reason": result.reason}

    @app.get("/v1/orchestrations/{orchestration_id}/audit")
    def audit(orchestration_id: str) -> Any:
        _guard(orchestration_id)
        return svc.audit(orchestration_id)

    # -- UI: rotas explícitas (precedem o mount de arquivos estáticos) ----------
    @app.get("/ui/", include_in_schema=False)
    def ui_macro() -> FileResponse:
        """Kanban Macro: visão global de todos os projetos e cards (tela inicial)."""
        return FileResponse(_STATIC_DIR / "macro.html")

    @app.get("/ui/nova", include_in_schema=False)
    def ui_nova() -> FileResponse:
        """Formulário focado de nova orquestração (sem outras orquestrações)."""
        return FileResponse(_STATIC_DIR / "nova.html")

    @app.get("/ui/detalhe", include_in_schema=False)
    def ui_detalhe() -> FileResponse:
        """Console/detalhe de uma orquestração individual (index.html original)."""
        return FileResponse(_STATIC_DIR / "index.html")

    # Montagem de arquivos estáticos (CSS/JS/etc.), se houver.
    if _STATIC_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")

    return app


# Instância padrão para `uvicorn aso.api.app:app` (usa ASO_DATABASE_URL se definido).
app = create_app(build_service())
