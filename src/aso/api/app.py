"""API v1 do ASO Runtime (FastAPI, TASK-13).

Adapter fino sobre o OrchestrationService: aqui só se compõe o gateway (correlation-id,
rate-limit, RBAC, tracing, log) e os routers por recurso de `aso.api.routers` (MEL-32,
ADR-0066). Contrato gerado do código em `contracts/openapi.json` (ADR-0064).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from structlog.contextvars import bind_contextvars, clear_contextvars

from aso.api.auth import AuthService, required_role
from aso.api.deps import ApiDeps
from aso.api.execucao_assincrona import criar_fila, execucao_assincrona_ativa
from aso.api.routers import (
    cards,
    catalogos,
    entrega,
    fluxo,
    implantacao,
    jobs,
    observabilidade,
    orquestracoes,
    preparacao,
    sistema,
    ui,
    workspace,
)
from aso.api.routers.ui import _STATIC_DIR
from aso.bootstrap import build_job_repository, build_service
from aso.control.orchestration_service import OrchestrationService
from aso.execution.jobs import JobRepository
from aso.execution.llm_client import LlmClient, build_llm_client_from_env
from aso.observability.broker import EventBroker
from aso.observability.logging import get_logger
from aso.observability.metrics import MetricsService
from aso.observability.ratelimit import RateLimiter
from aso.observability.tracing import get_tracer
from aso.shared.ids import gen_id

# Ordem de registro = ordem de casamento de rotas do Starlette; preservada do app.py
# monolítico (rotas de caminho fixo antes das de parâmetro no mesmo prefixo).
_ROUTERS = (
    sistema,
    workspace,
    orquestracoes,
    cards,
    fluxo,
    catalogos,
    implantacao,
    observabilidade,
    preparacao,
    entrega,
    jobs,
    ui,
)


def create_app(
    service: OrchestrationService | None = None,
    auth: AuthService | None = None,
    *,
    llm_client: LlmClient | None = None,
    execucao_assincrona: bool | None = None,
    job_repository: JobRepository | None = None,
) -> FastAPI:
    """Cria a aplicação FastAPI, opcionalmente com service/auth/llm/fila injetados.

    `execucao_assincrona` (padrão: `ASO_EXECUCAO_ASSINCRONA`) liga a fila de jobs: as rotas que
    acionam agentes respondem 202 e os workers executam (ADR-0067)."""
    svc = service or OrchestrationService()
    auth = auth or AuthService.from_env()
    # Cérebro do autopilot: cliente LLM injetado (testes) ou montado do ambiente.
    planning_client = llm_client or build_llm_client_from_env()
    metrics = MetricsService(svc)
    log = get_logger()
    tracer = get_tracer()
    limiter = RateLimiter.from_env()
    broker = EventBroker()
    assincrona = (
        execucao_assincrona if execucao_assincrona is not None else execucao_assincrona_ativa()
    )
    fila = (
        criar_fila(svc, job_repository or build_job_repository(), broker=broker)
        if assincrona
        else None
    )

    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI) -> AsyncIterator[None]:
        # Boot: recupera jobs órfãos e sobe os workers (os `queued` voltam a rodar).
        if fila is not None:
            fila.iniciar()
        yield
        if fila is not None:
            fila.parar()

    app = FastAPI(
        lifespan=ciclo_de_vida,
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
            # EventSource não envia headers; aceita token via query param `?token=` SÓ no
            # SSE (ADR-0057): em qualquer outra rota o token na URL vaza em log de acesso,
            # histórico e Referer sem necessidade.
            authz = request.headers.get("authorization")
            if (
                authz is None
                and path.endswith("/events/stream")
                and request.query_params.get("token")
            ):
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

    deps = ApiDeps(
        svc=svc, metrics=metrics, broker=broker, planning_client=planning_client, fila=fila
    )
    for modulo in _ROUTERS:
        app.include_router(modulo.criar_router(deps))

    # Montagem de arquivos estáticos (CSS/JS/etc.), se houver.
    if _STATIC_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")

    return app


# Instância padrão para `uvicorn aso.api.app:app` (usa ASO_DATABASE_URL se definido).
app = create_app(build_service())
