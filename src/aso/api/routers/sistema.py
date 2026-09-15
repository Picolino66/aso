"""Rotas de sistema: saúde, métricas Prometheus, identidade e catálogos estáticos.

Extraídas do `create_app` monolítico no MEL-32 passo 10 (ADR-0066).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from aso.api.deps import ApiDeps
from aso.control.next_step import phase_catalog


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()
    metrics = deps.metrics

    @router.get("/health")
    def health() -> Any:
        return {"status": "ok"}

    @router.get("/metrics")
    def prometheus_metrics() -> Response:
        return Response(content=metrics.prometheus(), media_type="text/plain; version=0.0.4")

    @router.get("/")
    def root() -> Any:
        return {
            "name": "ASO Runtime",
            "version": "1.0.0",
            "ui": "/ui/",
            "docs": "/docs",
            "redoc": "/redoc",
            "openapi": "/openapi.json",
        }

    @router.get("/v1/me")
    def me(request: Request) -> Any:
        """Identidade do principal autenticado (wf §2.3, "Perfil do usuário",
        ADR-0035) — sem isto o frontend não tem como saber quem está logado além
        de "existe um token salvo"."""
        principal = request.state.principal
        return {"actor": principal.actor, "role": principal.role}

    @router.get("/v1/phases")
    def list_phases() -> Any:
        """Catálogo da esteira F1..F7 com descrição didática (ADR-0015).

        Estático: a UI monta os passos a partir daqui em vez de repetir os textos.
        """
        return phase_catalog()

    return router
