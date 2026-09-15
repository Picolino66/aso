"""Rotas de workspace: navegador de pastas, pré-análise e docs-first (ADR-0062).

Extraídas do `create_app` monolítico no MEL-32 passo 10 (ADR-0066).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from aso.api.deps import ApiDeps
from aso.api.execucao_assincrona import OP_ANALYZE_FOLDER, OP_DOCS_HEAL
from aso.api.schemas import (
    AnalyzeFolderBody,
)
from aso.execution.workspace import WorkspaceError, WorkspaceRootError, WorkspaceService


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()
    svc = deps.svc

    @router.get("/v1/fs/dirs")
    def list_dirs(path: str | None = Query(default=None)) -> Any:
        """Lista subdiretórios (navegador de pastas da UI). Só nomes/paths de pastas."""
        try:
            return WorkspaceService().list_dirs(path)
        except WorkspaceRootError as exc:  # fora da raiz é pedido inválido, não "não existe"
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.get("/v1/fs/analyze/stream")
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

    @router.post("/v1/orchestrations/{orchestration_id}/analyze-folder", status_code=201)
    def analyze_folder(
        orchestration_id: str, request: Request, body: AnalyzeFolderBody | None = None
    ) -> Any:
        """Analisa a pasta da orquestração e gera/atualiza a documentação docs-first."""
        deps.guard(orchestration_id)
        body = body or AnalyzeFolderBody()
        if deps.fila is not None:
            return deps.enfileirar(
                OP_ANALYZE_FOLDER, orchestration_id, request, parametros=body.model_dump()
            )
        try:
            return svc.analyze_folder(
                orchestration_id,
                executor=body.executor,
                effort=body.effort,
                inicializar_git=body.inicializar_git,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except (ValueError, WorkspaceError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.get("/v1/orchestrations/{orchestration_id}/docs-drift")
    def docs_drift(orchestration_id: str) -> Any:
        """Relatório de drift entre a documentação docs-first e o código (só leitura)."""
        deps.guard(orchestration_id)
        try:
            return svc.docs_drift(orchestration_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except (ValueError, WorkspaceError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.post("/v1/orchestrations/{orchestration_id}/docs-heal", status_code=201)
    def docs_heal(
        orchestration_id: str, request: Request, body: AnalyzeFolderBody | None = None
    ) -> Any:
        """Sincroniza (self-heal) a documentação docs-first com o código do workspace."""
        deps.guard(orchestration_id)
        body = body or AnalyzeFolderBody()
        if deps.fila is not None:
            return deps.enfileirar(
                OP_DOCS_HEAL, orchestration_id, request, parametros=body.model_dump()
            )
        try:
            return svc.heal_docs(
                orchestration_id,
                executor=body.executor,
                effort=body.effort,
                inicializar_git=body.inicializar_git,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except (ValueError, WorkspaceError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    return router
