"""Dependências compartilhadas pelos routers da API (MEL-32 passo 10, ADR-0066).

Antes, `create_app` era um único closure de ~2.200 linhas: os helpers de erro e o serviço
ficavam capturados por todas as 200 rotas. Agora cada router recebe um `ApiDeps` explícito
e os helpers de mapeamento de erro vivem aqui, num lugar só — sem regra de negócio.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NoReturn

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from aso.application.orchestration_service import OrchestrationService
from aso.application.project_service import ProjectNotFoundError, ProjectValidationError
from aso.control.documento import DocumentoError
from aso.execution.jobs import FilaDeJobs
from aso.execution.llm_client import LlmClient
from aso.observability.broker import EventBroker
from aso.observability.metrics import MetricsService


@dataclass(frozen=True)
class ApiDeps:
    """O que as rotas podem usar: serviço, métricas, broker SSE e cliente de planejamento."""

    svc: OrchestrationService
    metrics: MetricsService
    broker: EventBroker
    planning_client: LlmClient | None
    # Fila de execução assíncrona (ADR-0067); `None` = rotas de execução síncronas.
    fila: FilaDeJobs | None = None

    def enfileirar(
        self,
        operacao: str,
        orchestration_id: str,
        request: Request,
        *,
        card_id: str | None = None,
        parametros: dict[str, Any] | None = None,
    ) -> JSONResponse:
        """Enfileira a execução e responde `202 Accepted` com o job (acompanhe por polling)."""
        assert self.fila is not None  # noqa: S101 - só chamado quando a fila existe
        self.fila.iniciar()  # idempotente: sobe os workers se o lifespan não subiu
        job = self.fila.enfileirar(
            operacao,
            orchestration_id,
            card_id=card_id,
            parametros=parametros,
            ator=actor_de(request),
        )
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job.id,
                "status": job.status,
                "operacao": job.operacao,
                "acompanhar": f"/v1/jobs/{job.id}",
            },
        )

    def guard(self, orchestration_id: str) -> None:
        try:
            self.svc.get(orchestration_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Orquestração inexistente") from None

    def card_op(self, orchestration_id: str, fn: Callable[[], Any]) -> Any:
        self.guard(orchestration_id)
        try:
            return fn()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    def documento_op(self, orchestration_id: str, fn: Callable[[], Any]) -> Any:
        """Mesmo padrão de `card_op`, com `DocumentoError` (tipo/vocabulário
        inválido) mapeado para 400 — checado ANTES de `ValueError` genérico, já
        que `DocumentoError` é subclasse dele (mesmo cuidado de `RoutingRuleError`,
        ADR-0028)."""
        self.guard(orchestration_id)
        try:
            return fn()
        except DocumentoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None


def actor_de(request: Request) -> str:
    return str(request.state.principal.actor)


def raise_project_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ProjectNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from None
    if isinstance(exc, ProjectValidationError):
        raise HTTPException(status_code=400, detail=str(exc)) from None
    raise HTTPException(status_code=409, detail=str(exc)) from None


def exigir_admin_para_comando(request: Request, comando: str | None) -> None:
    """Comando de validação no corpo = comando no host (ADR-0057): exige admin.

    `required_role` decide pelo caminho; aqui a mesma rota é de operator quando
    não traz comando e de admin quando traz (padrão de `report_review`)."""
    if comando and comando.strip() and not request.state.principal.can("admin"):
        raise HTTPException(
            status_code=403,
            detail="Definir comando de validação (executa no host) exige papel admin.",
        )
