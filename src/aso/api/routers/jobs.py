"""Rotas da fila de execução assíncrona: acompanhar e cancelar jobs (ADR-0067, MEL-31)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from aso.api.deps import ApiDeps, actor_de
from aso.execution.jobs import FilaDeJobs

_DESLIGADA = "Execução assíncrona desligada (ASO_EXECUCAO_ASSINCRONA=1 liga a fila de jobs)."


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()

    def _fila() -> FilaDeJobs:
        if deps.fila is None:
            raise HTTPException(status_code=404, detail=_DESLIGADA)
        return deps.fila

    @router.get("/v1/jobs/{job_id}")
    def get_job(job_id: str) -> Any:
        """Estado do job (`queued`/`running`/`done`/`failed`/`cancelled`) e o resultado."""
        job = _fila().obter(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job inexistente: {job_id}")
        return job

    @router.get("/v1/orchestrations/{orchestration_id}/jobs")
    def list_jobs(orchestration_id: str, status: str | None = None) -> Any:
        """Jobs da orquestração em ordem de chegada (a fila que o console mostra)."""
        deps.guard(orchestration_id)
        return _fila().listar(orchestration_id=orchestration_id, status=status)

    @router.post("/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, request: Request) -> Any:
        """Cancela: na fila, nunca roda; rodando, o subprocess do agente é encerrado e o card
        é liberado pelo próprio fluxo de execução (claim, ADR-0058)."""
        try:
            return _fila().cancelar(job_id, ator=actor_de(request))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    return router
