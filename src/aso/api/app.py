"""API v1 do ASO Runtime (FastAPI, TASK-13).

Adapter fino sobre o OrchestrationService. Contrato em contracts/openapi.yaml.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any, NoReturn

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from structlog.contextvars import bind_contextvars, clear_contextvars

from aso.agents.models import AgentDefinitionError
from aso.api.auth import AuthService, required_role
from aso.bootstrap import build_candidate_providers, build_service
from aso.control.documento import DocumentoError
from aso.control.models import Environment, ValidationCheck
from aso.control.next_step import phase_catalog
from aso.control.orchestration_service import OrchestrationService
from aso.control.planning import PlanningService
from aso.control.project_service import (
    ProjectConflictError,
    ProjectNotFoundError,
    ProjectValidationError,
)
from aso.control.routing_rules import RoutingAction, RoutingCondition, RoutingRuleError
from aso.control.triage import DemandBrief
from aso.execution.codex_discovery import CodexDiscoveryError
from aso.execution.gate_validation import GateCommandError
from aso.execution.llm_client import LlmClient, build_llm_client_from_env
from aso.execution.workspace import WorkspaceError, WorkspaceService
from aso.governance.models import ContextPatch, SloEvaluation
from aso.observability.aprendizado import recomendacoes_estruturadas
from aso.observability.broker import EventBroker
from aso.observability.logging import get_logger
from aso.observability.metrics import MetricsService
from aso.observability.ratelimit import RateLimiter
from aso.observability.tracing import get_tracer
from aso.shared.ids import gen_id
from aso.shared.types import CardType, ExecutionMode, PatchType, Phase, RiskLevel

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
    # Tela 03 (Cadastro completo, wf §5.2, ADR-0039): quando presente, a ficha é
    # usada tal como enviada — SEM re-triagem (o solicitante já preencheu a ficha
    # à mão; rodar o agente de triagem por cima descartaria isso). Ausente
    # (comportamento de sempre, ex. `nova.html`): a demanda em texto livre passa
    # pela triagem normalmente (`create_with_triage`).
    demand_brief: dict[str, Any] | None = None
    # Tela 03: orçamento definido já na criação, em vez de só depois via
    # `PUT .../budget`. `None` preserva o default de ambiente de sempre.
    orcamento_usd: float | None = None


class AnalyzeFolderBody(BaseModel):
    executor: str | None = None
    effort: str | None = None


class ExecutionSettingsBody(BaseModel):
    executor: str | None = None
    effort: str | None = None
    validation_command: str | None = None


class AgentAssignmentBody(BaseModel):
    """Executor de uma etapa da esteira (ou do nomeador). Effort vazio = o do perfil."""

    executor: str
    effort: str | None = None


class RetriageBody(BaseModel):
    """Re-triagem (POST .../brief): agente opcional, cai na resolução padrão sem ele."""

    executor: str | None = None
    effort: str | None = None


class ClassificationBody(BaseModel):
    """Edição pontual da classificação (Tela 05, wf §7, ADR-0044) — todos os campos
    opcionais, só os informados mudam."""

    tipo: str | None = None
    risco: RiskLevel | None = None
    complexidade: str | None = None
    impactos: list[str] | None = None
    dominios: list[str] | None = None


class DiscoveryRunBody(BaseModel):
    """Roda o discovery (POST .../discovery/run); tudo opcional."""

    executor: str | None = None
    effort: str | None = None


class DiscoveryDecideBody(BaseModel):
    """Decide a aprovação humana do discovery (ADR-0020, §4)."""

    approved: bool
    comentario: str = ""


class SpecRunBody(BaseModel):
    """Gera/regenera a especificação (POST .../spec/run); tudo opcional."""

    executor: str | None = None
    effort: str | None = None


class SpecReviewBody(BaseModel):
    """Roda a revisão documental sobre a especificação corrente (ADR-0021, §6)."""

    executor: str | None = None


class SpecApproveBody(BaseModel):
    """Decisão humana da especificação quando o ciclo do §6 escalou (ADR-0021, §4.4)."""

    approved: bool
    comentario: str = ""


class DocumentoSaveBody(BaseModel):
    """Salva uma nova versão de um documento (Tela 08, wf §10.3, ADR-0046)."""

    conteudo_markdown: str
    autor: str
    referencias_codigo: list[str] = []
    referencias_cards: list[str] = []
    referencias_documentos: list[str] = []


class DocumentoReviewBody(BaseModel):
    """Roda o checklist do revisor sobre a versão corrente (wf §11, ADR-0046)."""

    executor: str | None = None


class DocumentoCommentBody(BaseModel):
    """Comentário ancorado num documento — os 8 campos do wf §10.3/§11.3."""

    autor: str
    tipo: str
    severidade: str
    descricao: str
    trecho_relacionado: str = ""
    acao_solicitada: str = ""


class DocumentoCommentResolveBody(BaseModel):
    resposta_do_autor: str = ""


class ValidationCheckBody(BaseModel):
    """Uma verificação nomeada da bateria do §12 (ADR-0022)."""

    nome: str
    comando: str
    categoria: str = "testes"
    bloqueante: bool = True


class ValidationChecksBody(BaseModel):
    """Substitui a bateria inteira (PUT .../validation-checks)."""

    checks: list[ValidationCheckBody]


class DeployConfigBody(BaseModel):
    """Configura a implantação (ADR-0023, §18-22); tudo opcional — só altera o
    que for enviado, mesmo padrão de `ExecutionSettingsBody`."""

    command: str | None = None
    environment: str | None = None
    health_checks: list[ValidationCheckBody] | None = None
    rollback_command: str | None = None


class DeployRunBody(BaseModel):
    """Roda a implantação (POST .../deploy/run); tudo opcional.

    `estagio` só tem efeito com pipeline configurado (§19, ADR-0029): nomeia qual
    estágio rodar; omitido, resolve para o primeiro pendente (avanço governado).
    """

    environment: str | None = None
    estagio: str | None = None
    versao_app: str = ""
    commit: str = ""
    branch: str = ""


class EnvironmentBody(BaseModel):
    """Um estágio do pipeline de implantação (§19, wf §25, ADR-0029)."""

    chave: str
    nome: str = ""
    ordem: int = 1
    comando: str | None = None
    health_checks: list[ValidationCheckBody] = []
    rollback_command: str | None = None
    requer_aprovacao_humana: bool = False


class DeployPipelineBody(BaseModel):
    """Configura o pipeline inteiro (PUT .../deploy/pipeline) — lista vazia volta
    ao monoambiente legado (ADR-0023)."""

    estagios: list[EnvironmentBody] = []


class DeployApproveBody(BaseModel):
    """Aceite final da implantação (ADR-0023, §22) — ação crítica, exige admin."""

    approved: bool
    comentario: str = ""
    # Sub-tipo do aceite humano (Tela 26, wf §28.2, ADR-0050) — opcional.
    tipo_aceite: str = ""


class DeployRollbackBody(BaseModel):
    """Reverte a última implantação (ADR-0023, §21) — ação crítica, exige admin."""

    reason: str
    # Estratégia escolhida (Tela 25, wf §27.1, ADR-0050) — opcional, descritiva.
    estrategia: str = ""


class IncidentInvestigateBody(BaseModel):
    """Marca um incidente como em investigação (§21, ADR-0032)."""

    detalhe: str = ""


class IncidentResolveBody(BaseModel):
    """Resolve um incidente com a causa raiz identificada (§21, ADR-0032)."""

    causa_raiz: str


class BudgetBody(BaseModel):
    """Eleva (ou remove) o teto de gasto (ADR-0026) — ação crítica, exige admin."""

    teto_usd: float | None = None


class QaCheckBody(BaseModel):
    """Registra uma verificação manual de QA (§16, plano de teste do wf §22.1,
    ADR-0049)."""

    cenario: str
    titulo: str = ""
    pre_condicoes: str = ""
    passos: list[str] = []
    ambiente: str = ""
    resultado_esperado: str = ""
    resultado_obtido: str = ""
    evidencias: list[str] = []
    gravidade: str = "media"
    status: str = "pendente"
    tipo_responsavel: str = "humano"


class QaFailBody(BaseModel):
    """Reprova uma verificação de QA já registrada (§17) — cria o bug vinculado."""

    resultado_obtido: str = ""
    evidencias: list[str] = []
    gravidade: str | None = None


class BugReportBody(BaseModel):
    """Registro manual de bug (Tela 21, wf §23, ADR-0049)."""

    titulo: str
    cenario: str = ""
    passos_para_reproduzir: list[str] = []
    ambiente: str = ""
    resultado_atual: str = ""
    resultado_esperado: str = ""
    evidencias: list[str] = []
    gravidade: str = "media"
    impacto: str = ""
    frequencia: str = ""
    agente_sugerido: str = ""
    retorno_de_fluxo: str = "retornar_implementacao"


class RunReviewBody(BaseModel):
    """Roda o agente revisor sobre o diff da PR (POST .../review/run); tudo opcional."""

    executor: str | None = None
    effort: str | None = None


class ReviewStatusBody(BaseModel):
    """Reporta o resultado da revisão (ADR-0017): `justificativa` exige papel admin."""

    status: str
    justificativa: str = ""


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


class RoutingRuleBody(BaseModel):
    """Corpo de criação/edição de uma regra de roteamento (§33, ADR-0028)."""

    nome: str
    descricao: str = ""
    ativa: bool = True
    precedencia: int = 100
    condicoes: list[RoutingCondition] = []
    acao: RoutingAction = RoutingAction()


class RoutingRulePreviewBody(BaseModel):
    """Corpo da pré-visualização (Tela 31, wf §33.2, ADR-0042) — regra ainda não
    salva, só as condições (e opcionalmente a ação, ignorada pelo match)."""

    condicoes: list[RoutingCondition] = []
    acao: RoutingAction = RoutingAction()


class RoutingRuleReorderBody(BaseModel):
    """Nova ordem visual das regras (Tela 31, ADR-0042) — lista de ids."""

    ordem: list[str]


class AgentDefinitionBody(BaseModel):
    """Corpo de criação/edição de uma definição de agente (Tela 30, wf §32,
    ADR-0053) — ação crítica (fonte de verdade das permissões reais), exige
    papel admin.

    Os campos de lista usam `None` (ausente/omitido no JSON), não `[]`, como
    default — bug real (code-review ultra): com default `[]`, um PUT que só
    queria mudar `nome`/`ativo` e omitiu `ferramentas`/`permissoes` revogava
    silenciosamente as permissões reais do papel (`AgentRegistry.seed_from_catalog`
    aplica exatamente o que está aqui). `create_agent_definition` continua
    tratando `None` como lista vazia (definição nova sem nada configurado ainda);
    `update_agent_definition` trata `None` como "não mude este campo" — só uma
    lista explícita (inclusive `[]` explícito) substitui o valor atual.
    """

    nome: str
    tipo: str = ""
    funcao: str = ""
    plataforma: str = ""
    role: str = ""
    modelos_permitidos: list[str] | None = None
    efforts_permitidos: list[str] | None = None
    ferramentas: list[str] | None = None
    permissoes: list[str] | None = None
    projetos: list[str] | None = None
    categorias_tarefa: list[str] | None = None
    limite_custo_usd: float | None = None
    limite_tentativas: int | None = None
    exige_supervisao: bool = False
    ativo: bool = True


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


class CreateCardBody(BaseModel):
    """Tela 10 (Estrutura da demanda, wf §12, ADR-0040): cria um item em
    qualquer nível da hierarquia."""

    title: str
    type: CardType = CardType.TASK
    parent_id: str | None = None
    description: str = ""


class AssignAgentBody(BaseModel):
    agent: str


class MoveBody(BaseModel):
    to_column: str


class BlockBody(BaseModel):
    reason: str = ""


class PauseBody(BaseModel):
    """Pausar/retomar (Tela 15, wf §17.2, ADR-0048)."""

    pausado: bool = True


class AddContextBody(BaseModel):
    """Adicionar contexto (Tela 15, wf §17.2, ADR-0048)."""

    texto: str


class RequestHelpBody(BaseModel):
    """Solicitar ajuda (Tela 15, wf §17.2, ADR-0048)."""

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

    @app.get("/v1/me")
    def me(request: Request) -> Any:
        """Identidade do principal autenticado (wf §2.3, "Perfil do usuário",
        ADR-0035) — sem isto o frontend não tem como saber quem está logado além
        de "existe um token salvo"."""
        principal = request.state.principal
        return {"actor": principal.actor, "role": principal.role}

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
        newest_first: bool = Query(default=False),
    ) -> Any:
        _guard(orchestration_id)
        return svc.timeline_page(
            orchestration_id, page=page, page_size=page_size, newest_first=newest_first
        )

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

    @app.get("/v1/orchestrations/{orchestration_id}/cards/tree")
    def get_card_tree(orchestration_id: str) -> Any:
        """Tela 10 (Estrutura da demanda, wf §12, ADR-0040)."""
        return _card_op(orchestration_id, lambda: svc.get_card_tree(orchestration_id))

    @app.get("/v1/orchestrations/{orchestration_id}/kanban")
    def get_kanban_board(orchestration_id: str) -> Any:
        """Tela 11 (Kanban operacional, wf §13/§35, ADR-0047): as 16 colunas reais
        (rótulo do wireframe quando existe), cards com os 11 campos do §13.3 já
        resolvidos, e o grafo de transições válidas."""
        _guard(orchestration_id)
        return svc.kanban_board(orchestration_id)

    @app.post("/v1/orchestrations/{orchestration_id}/cards", status_code=201)
    def create_card(orchestration_id: str, body: CreateCardBody) -> Any:
        """Tela 10 (wf §12, ADR-0040): cria um item em qualquer nível,
        respeitando a hierarquia (`parent_id` inexistente, ciclo ou profundidade
        excedida devolvem 409 — mesma validação de `BoardService.add_card`)."""
        return _card_op(
            orchestration_id,
            lambda: svc.create_card(
                orchestration_id,
                title=body.title,
                type=body.type,
                parent_id=body.parent_id,
                description=body.description,
            ),
        )

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

    # ---- Regras de roteamento (§33, ADR-0028) --------------------------------

    @app.get("/v1/routing-rules")
    def list_routing_rules(only_active: bool = Query(default=False)) -> Any:
        """Regras SE/ENTÃO avaliadas antes da heurística do decision engine."""
        return svc.list_routing_rules(only_active=only_active)

    @app.post("/v1/routing-rules", status_code=201)
    def create_routing_rule(body: RoutingRuleBody, request: Request) -> Any:
        """Cria uma regra de roteamento (ação crítica — exige papel admin)."""
        try:
            return svc.create_routing_rule(
                nome=body.nome,
                descricao=body.descricao,
                ativa=body.ativa,
                precedencia=body.precedencia,
                condicoes=body.condicoes,
                acao=body.acao,
                actor=_actor(request),
            )
        except RoutingRuleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.post("/v1/routing-rules/preview")
    def preview_routing_rule(body: RoutingRulePreviewBody) -> Any:
        """Quais demandas já existentes casariam com esta regra ainda não salva
        (Tela 31, wf §33.2, ADR-0042)."""
        try:
            return svc.preview_routing_rule(condicoes=body.condicoes, acao=body.acao)
        except RoutingRuleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.put("/v1/routing-rules/reorder")
    def reorder_routing_rules(body: RoutingRuleReorderBody) -> Any:
        """Reordena por arrasta-e-solta, reatribuindo `precedencia` (Tela 31,
        ADR-0042). Registrada ANTES de `PUT .../{rule_id}` — `reorder` é um
        segmento literal e seria interceptado como `rule_id="reorder"` se viesse
        depois (Starlette casa rotas por ordem de registro; mesmo cuidado já
        aplicado a `cards/{card_id}` na ADR-0041)."""
        try:
            return svc.reorder_routing_rules(body.ordem)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @app.put("/v1/routing-rules/{rule_id}")
    def update_routing_rule(rule_id: str, body: RoutingRuleBody) -> Any:
        """Atualiza uma regra existente (ação crítica — exige papel admin)."""
        try:
            return svc.update_routing_rule(
                rule_id,
                nome=body.nome,
                descricao=body.descricao,
                ativa=body.ativa,
                precedencia=body.precedencia,
                condicoes=body.condicoes,
                acao=body.acao,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except RoutingRuleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.delete("/v1/routing-rules/{rule_id}")
    def delete_routing_rule(rule_id: str) -> Any:
        """Remove uma regra de roteamento (ação crítica — exige papel admin)."""
        try:
            svc.delete_routing_rule(rule_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return {"deleted": rule_id}

    # ---- Catálogo de agentes (Tela 30, wf §32, ADR-0053) ---------------------

    @app.get("/v1/agent-definitions")
    def list_agent_definitions(only_active: bool = Query(default=False)) -> Any:
        """13 campos por agente — fonte de verdade das permissões reais."""
        return svc.list_agent_definitions(only_active=only_active)

    @app.get("/v1/agent-definitions/roles")
    def get_agent_real_roles() -> Any:
        """Papéis reais do AgentRegistry, para vincular uma definição só a um
        `role` que de fato existe — registrada ANTES de `/{definition_id}`
        (segmento literal, mesmo cuidado de `routing-rules/reorder`, ADR-0042)."""
        return svc.get_agent_real_roles()

    @app.get("/v1/agent-definitions/{definition_id}")
    def get_agent_definition(definition_id: str) -> Any:
        try:
            return svc.get_agent_definition(definition_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @app.post("/v1/agent-definitions", status_code=201)
    def create_agent_definition(body: AgentDefinitionBody, request: Request) -> Any:
        """Cria uma definição de agente (ação crítica — exige papel admin)."""
        try:
            return svc.create_agent_definition(
                nome=body.nome,
                tipo=body.tipo,
                funcao=body.funcao,
                plataforma=body.plataforma,
                role=body.role,
                modelos_permitidos=body.modelos_permitidos,
                efforts_permitidos=body.efforts_permitidos,
                ferramentas=body.ferramentas,
                permissoes=body.permissoes,
                projetos=body.projetos,
                categorias_tarefa=body.categorias_tarefa,
                limite_custo_usd=body.limite_custo_usd,
                limite_tentativas=body.limite_tentativas,
                exige_supervisao=body.exige_supervisao,
                ativo=body.ativo,
                actor=_actor(request),
            )
        except AgentDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.put("/v1/agent-definitions/{definition_id}")
    def update_agent_definition(definition_id: str, body: AgentDefinitionBody) -> Any:
        """Atualiza uma definição existente (ação crítica — exige papel admin)."""
        try:
            return svc.update_agent_definition(
                definition_id,
                nome=body.nome,
                tipo=body.tipo,
                funcao=body.funcao,
                plataforma=body.plataforma,
                role=body.role,
                modelos_permitidos=body.modelos_permitidos,
                efforts_permitidos=body.efforts_permitidos,
                ferramentas=body.ferramentas,
                permissoes=body.permissoes,
                projetos=body.projetos,
                categorias_tarefa=body.categorias_tarefa,
                limite_custo_usd=body.limite_custo_usd,
                limite_tentativas=body.limite_tentativas,
                exige_supervisao=body.exige_supervisao,
                ativo=body.ativo,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except AgentDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.delete("/v1/agent-definitions/{definition_id}")
    def delete_agent_definition(definition_id: str) -> Any:
        """Remove uma definição de agente (ação crítica — exige papel admin)."""
        try:
            svc.delete_agent_definition(definition_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return {"deleted": definition_id}

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

    @app.get("/v1/orchestrations/{orchestration_id}/docs-drift")
    def docs_drift(orchestration_id: str) -> Any:
        """Relatório de drift entre a documentação docs-first e o código (só leitura)."""
        _guard(orchestration_id)
        try:
            return svc.docs_drift(orchestration_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except (ValueError, WorkspaceError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.get("/v1/orchestrations/{orchestration_id}/next-step")
    def next_step(orchestration_id: str) -> Any:
        """O que falta para a esteira seguir: checklist, bloqueios e ação primária.

        Fonte única de verdade das regras que travam o avanço (ADR-0013) — a tela de
        detalhe apenas renderiza este contrato.
        """
        _guard(orchestration_id)
        breaches = metrics.slo_report(orchestration_id).get("breaches", [])
        return svc.next_step(orchestration_id, slo_breaches=list(breaches))

    @app.post("/v1/orchestrations/{orchestration_id}/docs-heal", status_code=201)
    def docs_heal(orchestration_id: str, body: AnalyzeFolderBody | None = None) -> Any:
        """Sincroniza (self-heal) a documentação docs-first com o código do workspace."""
        _guard(orchestration_id)
        body = body or AnalyzeFolderBody()
        try:
            return svc.heal_docs(orchestration_id, executor=body.executor, effort=body.effort)
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

    @app.get("/v1/orchestrations/{orchestration_id}/validation-checks")
    def get_validation_checks(orchestration_id: str) -> Any:
        """Bateria efetiva de validações (§12 do fluxo.md, ADR-0022)."""
        _guard(orchestration_id)
        return svc.get_validation_checks(orchestration_id)

    @app.put("/v1/orchestrations/{orchestration_id}/validation-checks")
    def set_validation_checks(
        orchestration_id: str, body: ValidationChecksBody, request: Request
    ) -> Any:
        """Substitui a bateria — cada comando passa por `validate_gate_command`."""
        _guard(orchestration_id)
        try:
            return svc.set_validation_checks(
                orchestration_id,
                [ValidationCheck(**c.model_dump()) for c in body.checks],
                actor=_actor(request),
            )
        except GateCommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.get("/v1/orchestrations/{orchestration_id}/validation-checks/suggest")
    def suggest_validation_checks(orchestration_id: str) -> Any:
        """Sugestão determinística por stack (§4.5) — não grava nada."""
        _guard(orchestration_id)
        return svc.suggest_validation_checks(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/deploy")
    def get_deploy(orchestration_id: str) -> Any:
        """Última implantação (§18-22 do fluxo.md, ADR-0023)."""
        _guard(orchestration_id)
        return svc.get_deploy(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/deploy/history")
    def get_deploy_history(orchestration_id: str) -> Any:
        """Histórico de tentativas de implantação — ring de até 5."""
        _guard(orchestration_id)
        return svc.get_deploy_history(orchestration_id)

    @app.put("/v1/orchestrations/{orchestration_id}/deploy/config")
    def set_deploy_config(orchestration_id: str, body: DeployConfigBody, request: Request) -> Any:
        """Configura comando/ambiente/health checks/rollback da implantação."""
        _guard(orchestration_id)
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
                actor=_actor(request),
            )
        except GateCommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.get("/v1/orchestrations/{orchestration_id}/deploy/pipeline")
    def get_deploy_pipeline(orchestration_id: str) -> Any:
        """Status derivado por estágio (§19, wf §25, ADR-0029) — lista vazia =
        monoambiente legado, nenhum pipeline configurado."""
        _guard(orchestration_id)
        return svc.get_deploy_pipeline(orchestration_id)

    @app.put("/v1/orchestrations/{orchestration_id}/deploy/pipeline")
    def set_deploy_pipeline(
        orchestration_id: str, body: DeployPipelineBody, request: Request
    ) -> Any:
        """Configura o pipeline de estágios; lista vazia volta ao monoambiente
        legado (ADR-0023)."""
        _guard(orchestration_id)
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
                actor=_actor(request),
            )
        except GateCommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/v1/orchestrations/{orchestration_id}/deploy/run")
    def run_deploy(orchestration_id: str, body: DeployRunBody, request: Request) -> Any:
        """Roda a implantação — exige comando configurado e o quality gate mais
        recente aprovado (§18); o resultado decide aceite automático ou humano.
        Com pipeline configurado, `body.estagio` escolhe qual estágio rodar
        (omitido, resolve o primeiro pendente — avanço governado, §19)."""
        return _card_op(
            orchestration_id,
            lambda: svc.run_deploy(
                orchestration_id,
                environment=body.environment,
                estagio=body.estagio,
                versao_app=body.versao_app,
                commit=body.commit,
                branch=body.branch,
                actor=_actor(request),
            ),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/deploy/validate")
    def validate_deploy(orchestration_id: str, request: Request) -> Any:
        """Roda as verificações pós-implantação configuradas (§20)."""
        return _card_op(
            orchestration_id,
            lambda: svc.validate_deploy(orchestration_id, actor=_actor(request)),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/deploy/approve")
    def approve_deploy(orchestration_id: str, body: DeployApproveBody, request: Request) -> Any:
        """Aceite final da implantação (§22) — ação crítica, exige admin."""
        return _card_op(
            orchestration_id,
            lambda: svc.decide_deploy(
                orchestration_id,
                approved=body.approved,
                comentario=body.comentario,
                tipo_aceite=body.tipo_aceite,
                actor=_actor(request),
            ),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/deploy/rollback")
    def rollback_deploy(orchestration_id: str, body: DeployRollbackBody, request: Request) -> Any:
        """Reverte a última implantação e abre uma tarefa de causa raiz (§21)."""
        return _card_op(
            orchestration_id,
            lambda: svc.rollback_deploy(
                orchestration_id,
                reason=body.reason,
                estrategia=body.estrategia,
                actor=_actor(request),
            ),
        )

    # --- Telas 22/24/25/27 (aprovação, saúde, rollback, encerramento — ADR-0050) ---

    @app.get("/v1/orchestrations/{orchestration_id}/deploy/approval-checklist")
    def get_deploy_approval_checklist(orchestration_id: str) -> Any:
        """Checklist de 9 itens + avaliação de risco (Tela 22, wf §24)."""
        _guard(orchestration_id)
        return svc.get_deploy_approval_checklist(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/deploy/health")
    def get_deploy_health(orchestration_id: str) -> Any:
        """Saúde de 4 níveis + decisão sugerida (Tela 24, wf §26)."""
        return _card_op(orchestration_id, lambda: svc.get_deploy_health(orchestration_id))

    @app.get("/v1/orchestrations/{orchestration_id}/deploy/rollback-checklist")
    def get_rollback_checklist(orchestration_id: str) -> Any:
        """Checklist de 6 itens do rollback (Tela 25, wf §27)."""
        return _card_op(orchestration_id, lambda: svc.get_rollback_checklist(orchestration_id))

    @app.get("/v1/orchestrations/{orchestration_id}/closure")
    def get_demand_closure(orchestration_id: str) -> Any:
        """Relatório de encerramento da demanda, 13 blocos + métricas (Tela 27, wf §29)."""
        _guard(orchestration_id)
        return svc.get_demand_closure(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/closure/export")
    def export_demand_closure(orchestration_id: str) -> Any:
        """Markdown pronto para download (botão 'Exportar relatório', wf §29.2)."""
        _guard(orchestration_id)
        markdown = svc.export_demand_closure(orchestration_id)
        return Response(
            content=markdown,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="encerramento-{orchestration_id}.md"'
            },
        )

    # --- incidentes (§21, wf §27/§38, ADR-0032) ---

    @app.get("/v1/orchestrations/{orchestration_id}/incidents")
    def list_incidents(orchestration_id: str) -> Any:
        """Incidentes da orquestração — abertos automaticamente por rollback (§21)."""
        _guard(orchestration_id)
        return svc.list_incidents(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/incidents/{incident_id}")
    def get_incident(orchestration_id: str, incident_id: str) -> Any:
        _guard(orchestration_id)
        incident = svc.get_incident(orchestration_id, incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incidente inexistente")
        return incident

    @app.post("/v1/orchestrations/{orchestration_id}/incidents/{incident_id}/investigate")
    def investigate_incident(
        orchestration_id: str,
        incident_id: str,
        body: IncidentInvestigateBody,
        request: Request,
    ) -> Any:
        """Marca o incidente como em investigação."""
        return _card_op(
            orchestration_id,
            lambda: svc.investigate_incident(
                orchestration_id, incident_id, detalhe=body.detalhe, actor=_actor(request)
            ),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/incidents/{incident_id}/resolve")
    def resolve_incident(
        orchestration_id: str, incident_id: str, body: IncidentResolveBody, request: Request
    ) -> Any:
        """Resolve o incidente com a causa raiz identificada."""
        return _card_op(
            orchestration_id,
            lambda: svc.resolve_incident(
                orchestration_id, incident_id, causa_raiz=body.causa_raiz, actor=_actor(request)
            ),
        )

    @app.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/qa")
    def get_qa_checks(orchestration_id: str, card_id: str) -> Any:
        """Histórico de verificações manuais de QA do card (§16, ring de 10)."""
        return _card_op(orchestration_id, lambda: svc.get_qa_checks(orchestration_id, card_id))

    @app.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/checklist")
    def get_preparation_checklist(orchestration_id: str, card_id: str) -> Any:
        """Checklist de preparação para implementação (§10, ADR-0030) — só leitura."""
        return _card_op(
            orchestration_id, lambda: svc.get_preparation_checklist(orchestration_id, card_id)
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/qa")
    def register_qa_check(
        orchestration_id: str, card_id: str, body: QaCheckBody, request: Request
    ) -> Any:
        """Registra uma verificação manual de QA (§16)."""
        return _card_op(
            orchestration_id,
            lambda: svc.register_qa_check(
                orchestration_id,
                card_id,
                cenario=body.cenario,
                titulo=body.titulo,
                pre_condicoes=body.pre_condicoes,
                passos=body.passos,
                ambiente=body.ambiente,
                resultado_esperado=body.resultado_esperado,
                resultado_obtido=body.resultado_obtido,
                evidencias=body.evidencias,
                gravidade=body.gravidade,
                status=body.status,
                tipo_responsavel=body.tipo_responsavel,
                actor=_actor(request),
            ),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/qa/{index}/fail")
    def fail_qa_check(
        orchestration_id: str, card_id: str, index: int, body: QaFailBody, request: Request
    ) -> Any:
        """Reprova uma verificação de QA já registrada — cria o bug vinculado (§17)."""
        return _card_op(
            orchestration_id,
            lambda: svc.fail_qa_check(
                orchestration_id,
                card_id,
                index,
                resultado_obtido=body.resultado_obtido,
                evidencias=body.evidencias,
                gravidade=body.gravidade,
                actor=_actor(request),
            ),
        )

    @app.get("/v1/orchestrations/{orchestration_id}/learning")
    def get_learning_report(orchestration_id: str) -> Any:
        """Relatório de aprendizado da demanda (§24) — retrabalho, falhas por
        etapa, desempenho por executor, intervenções humanas. Informativo."""
        _guard(orchestration_id)
        return svc.get_learning_report(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/learning/recommendations")
    def get_learning_recommendations(orchestration_id: str) -> Any:
        """8 recomendações estruturadas da Tela 29 (wf §31.3, ADR-0052) — 6 com
        justificativa quando disparadas, 2 permanentemente desabilitadas."""
        _guard(orchestration_id)
        return recomendacoes_estruturadas(svc.get_learning_report(orchestration_id))

    @app.get("/v1/learning")
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

    @app.get("/v1/learning/recommendations")
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

    @app.put("/v1/orchestrations/{orchestration_id}/budget")
    def set_budget(orchestration_id: str, body: BudgetBody, request: Request) -> Any:
        """Eleva/remove o teto de orçamento (§1.2/§3.2, ADR-0026) — ação crítica,
        exige admin (`/budget` no sufixo administrativo de `api/auth.py`)."""
        return _card_op(
            orchestration_id,
            lambda: svc.set_orcamento(orchestration_id, body.teto_usd, actor=_actor(request)),
        )

    @app.get("/v1/orchestrations/{orchestration_id}/worktrees")
    def list_worktrees(orchestration_id: str) -> Any:
        """Worktrees em disco desta orquestração, com `orfao` marcado (§3.3, ADR-0027)."""
        _guard(orchestration_id)
        return svc.list_worktrees(orchestration_id)

    @app.post("/v1/orchestrations/{orchestration_id}/worktrees/prune")
    def prune_worktrees(orchestration_id: str, request: Request) -> Any:
        """Remove os worktrees órfãos (não referenciados por card ativo) — nunca
        `rm -rf`, exige admin: pode destruir trabalho de agente não mesclado."""
        return _card_op(
            orchestration_id,
            lambda: svc.prune_worktrees(orchestration_id, actor=_actor(request)),
        )

    @app.get("/v1/phases")
    def list_phases() -> Any:
        """Catálogo da esteira F1..F7 com descrição didática (ADR-0015).

        Estático: a UI monta os passos a partir daqui em vez de repetir os textos.
        """
        return phase_catalog()

    @app.get("/v1/orchestrations/{orchestration_id}/agent-log")
    def agent_log(
        orchestration_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=500, ge=1, le=2000),
    ) -> Any:
        """Saída ao vivo dos agentes desta orquestração; `after` é o cursor."""
        _guard(orchestration_id)
        return svc.agent_log(orchestration_id, after=after, limit=limit)

    @app.put("/v1/orchestrations/{orchestration_id}/agents/{key}")
    def set_agent_assignment(
        orchestration_id: str, key: str, body: AgentAssignmentBody, request: Request
    ) -> Any:
        """Define o executor de uma etapa (F1..F7) ou do nomeador de branches/commits."""
        _guard(orchestration_id)
        try:
            return svc.set_agent_assignment(
                orchestration_id,
                key,
                executor=body.executor,
                effort=body.effort,
                actor=_actor(request),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.delete("/v1/orchestrations/{orchestration_id}/agents/{key}")
    def clear_agent_assignment(orchestration_id: str, key: str, request: Request) -> Any:
        """Remove o executor da etapa: ela volta a herdar o padrão da orquestração."""
        _guard(orchestration_id)
        try:
            return svc.clear_agent_assignment(orchestration_id, key, actor=_actor(request))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.get("/v1/orchestrations/{orchestration_id}/brief")
    def get_brief(orchestration_id: str) -> Any:
        """Ficha estruturada da demanda (§1/§2 do fluxo.md)."""
        _guard(orchestration_id)
        return svc.get_demand_brief(orchestration_id)

    @app.post("/v1/orchestrations/{orchestration_id}/brief")
    def retriage_brief(orchestration_id: str, body: RetriageBody, request: Request) -> Any:
        """Re-tria a demanda — útil depois que o operador responde `perguntas_abertas`."""
        _guard(orchestration_id)
        return svc.retriage_demand(
            orchestration_id, executor=body.executor, effort=body.effort, actor=_actor(request)
        )

    @app.patch("/v1/orchestrations/{orchestration_id}/classification")
    def update_classification(
        orchestration_id: str, body: ClassificationBody, request: Request
    ) -> Any:
        """Edição pontual da classificação, com auditoria antes/depois (Tela 05,
        wf §7, ADR-0044)."""
        return _card_op(
            orchestration_id,
            lambda: svc.update_classification(
                orchestration_id,
                tipo=body.tipo,
                risco=body.risco,
                complexidade=body.complexidade,
                impactos=body.impactos,
                dominios=body.dominios,
                actor=_actor(request),
            ),
        )

    @app.get("/v1/orchestrations/{orchestration_id}/recommendation")
    def get_recommendation(orchestration_id: str) -> Any:
        """Painel de recomendação (Tela 13, wf §15, ADR-0044) — o que o motor
        decidiria hoje para esta demanda; não persiste nada."""
        _guard(orchestration_id)
        return svc.preview_recommendation(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/discovery")
    def get_discovery(orchestration_id: str) -> Any:
        """Relatório de discovery atual (§3 do fluxo.md, ADR-0020)."""
        _guard(orchestration_id)
        return svc.get_discovery_report(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/discovery/history")
    def get_discovery_history(orchestration_id: str) -> Any:
        """Histórico de versões do discovery (§4.2, ADR-0021) — ring de até 5."""
        _guard(orchestration_id)
        return svc.get_discovery_history(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/discovery/approval-criteria")
    def get_discovery_approval_criteria(orchestration_id: str) -> Any:
        """Tela 07 (wf §9, ADR-0045): checklist de critérios + motivos da escalada."""
        _guard(orchestration_id)
        return svc.get_discovery_approval_criteria(orchestration_id)

    @app.post("/v1/orchestrations/{orchestration_id}/discovery/run")
    def run_discovery(orchestration_id: str, body: DiscoveryRunBody) -> Any:
        """Roda o discovery e aplica a regra de aprovação automática/humana (§4)."""
        return _card_op(
            orchestration_id,
            lambda: svc.run_discovery(orchestration_id, executor=body.executor, effort=body.effort),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/discovery/decide")
    def decide_discovery(orchestration_id: str, body: DiscoveryDecideBody, request: Request) -> Any:
        """Decide a aprovação humana do discovery (ação crítica — papel admin)."""
        return _card_op(
            orchestration_id,
            lambda: svc.decide_discovery(
                orchestration_id,
                approved=body.approved,
                comentario=body.comentario,
                actor=_actor(request),
            ),
        )

    @app.get("/v1/orchestrations/{orchestration_id}/spec")
    def get_spec(orchestration_id: str) -> Any:
        """Especificação corrente (§5 do fluxo.md, ADR-0021)."""
        _guard(orchestration_id)
        return svc.get_spec(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/spec/history")
    def get_spec_history(orchestration_id: str) -> Any:
        """Histórico de versões da especificação (§4.2, ADR-0021) — ring de até 5."""
        _guard(orchestration_id)
        return svc.get_spec_history(orchestration_id)

    @app.post("/v1/orchestrations/{orchestration_id}/spec/run")
    def run_spec(orchestration_id: str, body: SpecRunBody) -> Any:
        """Gera/regenera a especificação — exige discovery aprovado (§5)."""
        return _card_op(
            orchestration_id,
            lambda: svc.run_spec(orchestration_id, executor=body.executor, effort=body.effort),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/spec/review")
    def run_spec_review(orchestration_id: str, body: SpecReviewBody, request: Request) -> Any:
        """Roda a revisão documental (§6) sobre a especificação corrente."""
        return _card_op(
            orchestration_id,
            lambda: svc.run_spec_review(
                orchestration_id, executor=body.executor, actor=_actor(request)
            ),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/spec/approve")
    def approve_spec(orchestration_id: str, body: SpecApproveBody, request: Request) -> Any:
        """Decide a especificação quando o ciclo do §6 escalou (ação crítica — admin)."""
        return _card_op(
            orchestration_id,
            lambda: svc.approve_spec(
                orchestration_id,
                approved=body.approved,
                comentario=body.comentario,
                actor=_actor(request),
            ),
        )

    # ---- Documentos (Tela 08/09, wf §10/§11, ADR-0046) -----------------------

    @app.get("/v1/orchestrations/{orchestration_id}/documentos")
    def list_documentos(orchestration_id: str) -> Any:
        """Lista de documentos (wf §10.2) — os 8 tipos novos + os 5 já cobertos
        pela especificação, em modo leitura."""
        _guard(orchestration_id)
        return svc.list_documentos(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/documentos/{tipo}")
    def get_documento(orchestration_id: str, tipo: str) -> Any:
        return _documento_op(orchestration_id, lambda: svc.get_documento(orchestration_id, tipo))

    @app.get("/v1/orchestrations/{orchestration_id}/documentos/{tipo}/history")
    def get_documento_history(orchestration_id: str, tipo: str) -> Any:
        """Histórico de versões (wf §10.3) — ring de até 5."""
        return _documento_op(
            orchestration_id, lambda: svc.get_documento_history(orchestration_id, tipo)
        )

    @app.get("/v1/orchestrations/{orchestration_id}/documentos/{tipo}/diff")
    def diff_documento(orchestration_id: str, tipo: str, de: int, para: int) -> Any:
        """Comparação de versões (wf §10.3)."""
        return _documento_op(
            orchestration_id,
            lambda: svc.diff_documento(orchestration_id, tipo, de=de, para=para),
        )

    @app.put("/v1/orchestrations/{orchestration_id}/documentos/{tipo}")
    def save_documento(orchestration_id: str, tipo: str, body: DocumentoSaveBody) -> Any:
        """Salva uma nova versão (edição manual, wf §10.3)."""
        return _documento_op(
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

    @app.post("/v1/orchestrations/{orchestration_id}/documentos/{tipo}/review")
    def review_documento(
        orchestration_id: str, tipo: str, body: DocumentoReviewBody, request: Request
    ) -> Any:
        """Checklist do revisor (wf §11) — os quatro desfechos do §11.2."""
        return _documento_op(
            orchestration_id,
            lambda: svc.review_documento(
                orchestration_id, tipo, executor=body.executor, actor=_actor(request)
            ),
        )

    @app.get("/v1/orchestrations/{orchestration_id}/documentos/{tipo}/comments")
    def list_documento_comments(orchestration_id: str, tipo: str) -> Any:
        return _documento_op(
            orchestration_id, lambda: svc.list_documento_comments(orchestration_id, tipo)
        )

    @app.post("/v1/orchestrations/{orchestration_id}/documentos/{tipo}/comments", status_code=201)
    def create_documento_comment(
        orchestration_id: str, tipo: str, body: DocumentoCommentBody, request: Request
    ) -> Any:
        """Comentário ancorado (wf §10.3/§11.3) — os 8 campos literais do wireframe."""
        return _documento_op(
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
                actor=_actor(request),
            ),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/documentos/comments/{comment_id}/resolve")
    def resolve_documento_comment(
        orchestration_id: str,
        comment_id: str,
        body: DocumentoCommentResolveBody,
        request: Request,
    ) -> Any:
        return _documento_op(
            orchestration_id,
            lambda: svc.resolve_documento_comment(
                orchestration_id,
                comment_id,
                resposta_do_autor=body.resposta_do_autor,
                actor=_actor(request),
            ),
        )

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

    @app.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}")
    def get_card(orchestration_id: str, card_id: str) -> Any:
        """Tela 12 (Detalhes do card, wf §14, ADR-0041): ficha completa de um
        único card — usada pelas abas Resumo/Plano/Implementação/Arquivos/
        Testes/Dependências/Execuções. Registrada depois de todas as rotas
        literais de um segmento sob `cards/` (`tree`, `stats`, `by-status/...`)
        para não sombreá-las — Starlette casa rotas na ordem de registro."""
        return _card_op(orchestration_id, lambda: svc.get_card(orchestration_id, card_id))

    @app.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/events")
    def get_card_events(orchestration_id: str, card_id: str) -> Any:
        """Tela 12 (aba Histórico, ADR-0041): log de movimentações do card,
        append-only, nunca truncado — diferente dos rings de tentativas/falhas."""
        return _card_op(orchestration_id, lambda: svc.get_card_events(orchestration_id, card_id))

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

    # --- Header (wf §2.3, ADR-0035) ---
    @app.get("/v1/header-summary")
    def header_summary(project_id: str | None = Query(default=None)) -> Any:
        """Execuções ativas, falhas e aprovações pendentes — escopadas ao
        `project_id` quando informado, senão globais."""
        return svc.header_summary(project_id=project_id)

    @app.get("/v1/search")
    def search(
        q: str = Query(default=""),
        project_id: str | None = Query(default=None),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> Any:
        """Busca global (wf §2.3, "Campo de busca"): demanda, card ou documento."""
        return svc.search(q, project_id=project_id, limit=limit)

    # --- Dashboard (wf §3.3, Tela 01, ADR-0037) ---
    @app.get("/v1/dashboard-summary")
    def dashboard_summary(project_id: str | None = Query(default=None)) -> Any:
        """Demandas ativas/em execução/bloqueadas/falhas, cards por status e
        aprovações pendentes por tipo — escopados ao `project_id` quando informado."""
        return svc.dashboard_summary(project_id=project_id)

    @app.get("/v1/activity")
    def recent_activity(limit: int = Query(default=20, ge=1, le=100)) -> Any:
        """Atividade recente global (tipo, ator, horário) — diferente da timeline
        por orquestração."""
        return svc.recent_activity(limit=limit)

    @app.get("/v1/audit")
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

    @app.get("/v1/audit/export")
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

    @app.post("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/review/run")
    def run_review(orchestration_id: str, pr_id: str, body: RunReviewBody, request: Request) -> Any:
        """Roda o agente revisor sobre o diff real da PR e aplica o veredito (ADR-0017)."""
        return _card_op(
            orchestration_id,
            lambda: svc.run_review(
                orchestration_id,
                pr_id,
                executor=body.executor,
                effort=body.effort,
                actor=_actor(request),
            ),
        )

    @app.get("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/review")
    def get_review(orchestration_id: str, pr_id: str) -> Any:
        """Veredito completo da última revisão independente (§14)."""
        return _card_op(orchestration_id, lambda: svc.get_review(orchestration_id, pr_id))

    @app.post("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/review")
    def report_review(
        orchestration_id: str, pr_id: str, body: ReviewStatusBody, request: Request
    ) -> Any:
        """Reporta o resultado da revisão (governado, ADR-0017).

        Sobrepor com `justificativa` (sem veredito aprovado) é uma decisão humana que
        recusa/ignora o agente revisor: exige papel admin — `required_role` não enxerga
        o corpo da requisição, então a checagem fina do papel fica aqui.
        """
        if body.justificativa.strip() and not request.state.principal.can("admin"):
            raise HTTPException(
                status_code=403,
                detail="Aprovar com justificativa (sem veredito aprovado) exige papel admin.",
            )
        return _card_op(
            orchestration_id,
            lambda: svc.report_review(
                orchestration_id,
                pr_id,
                body.status,
                actor=_actor(request),
                justificativa=body.justificativa,
            ),
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

    # --- comentários de revisão ancorados em arquivo/linha (wf §20.3, ADR-0033) ---

    @app.get("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/comments")
    def list_review_comments(orchestration_id: str, pr_id: str) -> Any:
        """Comentários da PR — alimenta a lista de correções obrigatórias da tela 19."""
        return _card_op(orchestration_id, lambda: svc.list_review_comments(orchestration_id, pr_id))

    @app.post("/v1/orchestrations/{orchestration_id}/pulls/{pr_id}/comments/{comment_id}/resolve")
    def resolve_review_comment(
        orchestration_id: str, pr_id: str, comment_id: str, request: Request
    ) -> Any:
        """Resolução manual — além da auto-resolução quando uma rodada aprova."""
        return _card_op(
            orchestration_id,
            lambda: svc.resolve_review_comment(
                orchestration_id, pr_id, comment_id, actor=_actor(request)
            ),
        )

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

    @app.post("/v1/orchestrations/{orchestration_id}/duplicate", status_code=201)
    def duplicate_orchestration(orchestration_id: str, request: Request) -> Any:
        """Duplicar (Tela 02, wf §4.4, ADR-0038): nova orquestração a partir do
        `user_request`/projeto/execução da origem, re-triada do zero."""
        return _card_op(
            orchestration_id,
            lambda: svc.duplicate_orchestration(orchestration_id, actor=_actor(request)),
        )

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
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    def _documento_op(orchestration_id: str, fn: Any) -> Any:
        """Mesmo padrão de `_card_op`, com `DocumentoError` (tipo/vocabulário
        inválido) mapeado para 400 — checado ANTES de `ValueError` genérico, já
        que `DocumentoError` é subclasse dele (mesmo cuidado de `RoutingRuleError`,
        ADR-0028)."""
        _guard(orchestration_id)
        try:
            return fn()
        except DocumentoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/assign-agent")
    def assign_agent(orchestration_id: str, card_id: str, body: AssignAgentBody) -> Any:
        return _card_op(
            orchestration_id, lambda: svc.assign_agent(orchestration_id, card_id, body.agent)
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/move")
    def move_card(orchestration_id: str, card_id: str, body: MoveBody) -> Any:
        """Movimentação manual (Tela 11, wf §35, ADR-0047) — valida a transição
        contra a máquina de estados; automação interna do runtime não passa por
        aqui (chama `BoardService`/`svc.move_card` sem validação)."""
        return _card_op(
            orchestration_id,
            lambda: svc.move_card_validado(orchestration_id, card_id, body.to_column),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/block")
    def block_card(orchestration_id: str, card_id: str, body: BlockBody) -> Any:
        return _card_op(
            orchestration_id, lambda: svc.block_card(orchestration_id, card_id, body.reason)
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/unblock")
    def unblock_card(orchestration_id: str, card_id: str) -> Any:
        return _card_op(orchestration_id, lambda: svc.unblock_card(orchestration_id, card_id))

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/cancel")
    def cancel_card(orchestration_id: str, card_id: str, body: BlockBody) -> Any:
        """Cancela um card individualmente (§8 do fluxo.md, coluna `Cancelled`)."""
        return _card_op(
            orchestration_id, lambda: svc.cancel_card(orchestration_id, card_id, body.reason)
        )

    @app.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/failures")
    def get_card_failures(orchestration_id: str, card_id: str) -> Any:
        """Histórico de falhas do card (§13 do fluxo.md, ADR-0019)."""
        return _card_op(orchestration_id, lambda: svc.get_card_failures(orchestration_id, card_id))

    @app.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/closure")
    def get_card_closure(orchestration_id: str, card_id: str) -> Any:
        """Ficha de encerramento do card (§23 do fluxo.md, ADR-0021)."""
        return _card_op(orchestration_id, lambda: svc.get_card_closure(orchestration_id, card_id))

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/route")
    def route_card(orchestration_id: str, card_id: str) -> Any:
        """Aciona o roteamento de falha manualmente (ADR-0019) — para quando o
        automático parou por limite (bloqueado/escalado) e o operador já corrigiu a
        causa."""
        return _card_op(orchestration_id, lambda: svc.route_card(orchestration_id, card_id))

    # ---- Controles em voo (Tela 15, wf §17.2, ADR-0048) -----------------------

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/pause")
    def pause_card(orchestration_id: str, card_id: str, body: PauseBody, request: Request) -> Any:
        """Pausar/retomar — impede a próxima execução, não interrompe uma em
        andamento (reinterpretação honesta, ver ADR-0048)."""
        return _card_op(
            orchestration_id,
            lambda: svc.pause_card(
                orchestration_id, card_id, pausado=body.pausado, actor=_actor(request)
            ),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/add-context")
    def add_card_context(
        orchestration_id: str, card_id: str, body: AddContextBody, request: Request
    ) -> Any:
        """Adicionar contexto — entra no próximo prompt do agente."""
        return _card_op(
            orchestration_id,
            lambda: svc.add_card_context(
                orchestration_id, card_id, body.texto, actor=_actor(request)
            ),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/increase-effort")
    def increase_card_effort(orchestration_id: str, card_id: str, request: Request) -> Any:
        """Aumentar effort — reaproveita `proximo_effort` (mesma função do
        roteamento automático de falha)."""
        return _card_op(
            orchestration_id,
            lambda: svc.increase_card_effort(orchestration_id, card_id, actor=_actor(request)),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/transfer-model")
    def transfer_card_model(orchestration_id: str, card_id: str, request: Request) -> Any:
        """Trocar modelo — reaproveita `proximo_executor` (mesma função do
        roteamento automático de falha)."""
        return _card_op(
            orchestration_id,
            lambda: svc.transfer_card_model(orchestration_id, card_id, actor=_actor(request)),
        )

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/request-help")
    def request_card_help(orchestration_id: str, card_id: str, body: RequestHelpBody) -> Any:
        """Solicitar ajuda — reaproveita `request_approval` (ação rotulada)."""
        return _card_op(
            orchestration_id,
            lambda: svc.request_card_help(orchestration_id, card_id, reason=body.reason),
        )

    @app.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/changed-files")
    def get_card_changed_files(orchestration_id: str, card_id: str) -> Any:
        """Arquivos alterados (Tela 15, wf §17.1) — diff real da branch do card."""
        return _card_op(
            orchestration_id, lambda: svc.get_card_changed_files(orchestration_id, card_id)
        )

    @app.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/failure-diagnostics")
    def get_card_failure_diagnostics(orchestration_id: str, card_id: str) -> Any:
        """Tela 17 (wf §19): falhas com diagnóstico e confiança calculados na leitura."""
        return _card_op(
            orchestration_id,
            lambda: svc.get_card_failure_diagnostics(orchestration_id, card_id),
        )

    @app.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/diff-stats")
    def get_card_diff_stats(orchestration_id: str, card_id: str) -> Any:
        """Resumo do review — commits/arquivos/linhas (Tela 18, wf §20.1, ADR-0049)."""
        return _card_op(
            orchestration_id, lambda: svc.get_card_diff_stats(orchestration_id, card_id)
        )

    # --- bugs manuais (Tela 21, wf §23, ADR-0049) ---

    @app.get("/v1/orchestrations/{orchestration_id}/bug-reports")
    def list_bug_reports(orchestration_id: str) -> Any:
        """Todos os bugs registrados manualmente na orquestração."""
        _guard(orchestration_id)
        return svc.list_bug_reports(orchestration_id)

    @app.get("/v1/orchestrations/{orchestration_id}/bug-reports/{bug_report_id}")
    def get_bug_report(orchestration_id: str, bug_report_id: str) -> Any:
        _guard(orchestration_id)
        report = svc.get_bug_report(orchestration_id, bug_report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Registro de bug inexistente")
        return report

    @app.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/bug-reports")
    def list_bug_reports_do_card(orchestration_id: str, card_id: str) -> Any:
        """Bugs registrados contra este card (`card_original_id`)."""
        _guard(orchestration_id)
        return svc.list_bug_reports(orchestration_id, card_id)

    @app.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/bug-reports")
    def create_bug_report(
        orchestration_id: str, card_id: str, body: BugReportBody, request: Request
    ) -> Any:
        """Registro manual de bug (Tela 21, wf §23) — cria o card Bug vinculado."""
        return _card_op(
            orchestration_id,
            lambda: svc.create_bug_report(
                orchestration_id,
                card_id,
                titulo=body.titulo,
                cenario=body.cenario,
                passos_para_reproduzir=body.passos_para_reproduzir,
                ambiente=body.ambiente,
                resultado_atual=body.resultado_atual,
                resultado_esperado=body.resultado_esperado,
                evidencias=body.evidencias,
                gravidade=body.gravidade,
                impacto=body.impacto,
                frequencia=body.frequencia,
                agente_sugerido=body.agente_sugerido,
                retorno_de_fluxo=body.retorno_de_fluxo,
                actor=_actor(request),
            ),
        )

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
    def list_approvals(
        status: str | None = Query(default=None),
        project_id: str | None = Query(default=None),
    ) -> Any:
        approvals = svc.list_all_approvals()
        if status is not None:
            approvals = [a for a in approvals if a.status == status]
        if project_id is not None:
            ids = {o.id for o in svc.list_all(project_id=project_id)}
            approvals = [a for a in approvals if a.orchestration_id in ids]
        return approvals

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
        """Sala de controle de UMA orquestração: fase, próximo passo e pendências."""
        return FileResponse(_STATIC_DIR / "detalhe.html")

    @app.get("/ui/console", include_in_schema=False)
    def ui_console() -> FileResponse:
        """Console técnico completo (abas de auditoria) — mantido para operação avançada."""
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/ui/demanda-nova", include_in_schema=False)
    def ui_demanda_nova() -> FileResponse:
        """Tela 03 — cadastro completo de demanda (wf §5.2, ADR-0039)."""
        return FileResponse(_STATIC_DIR / "demanda-nova.html")

    @app.get("/ui/demanda-estrutura", include_in_schema=False)
    def ui_demanda_estrutura() -> FileResponse:
        """Tela 10 — estrutura da demanda em árvore (wf §12, ADR-0040)."""
        return FileResponse(_STATIC_DIR / "demanda-estrutura.html")

    @app.get("/ui/card-detalhe", include_in_schema=False)
    def ui_card_detalhe() -> FileResponse:
        """Tela 12 — detalhes do card com 10 abas (wf §14, ADR-0041)."""
        return FileResponse(_STATIC_DIR / "card-detalhe.html")

    @app.get("/ui/regras-roteamento", include_in_schema=False)
    def ui_regras_roteamento() -> FileResponse:
        """Tela 31 — editor visual de regras de roteamento (wf §33, ADR-0042)."""
        return FileResponse(_STATIC_DIR / "regras-roteamento.html")

    @app.get("/ui/demanda-detalhe", include_in_schema=False)
    def ui_demanda_detalhe() -> FileResponse:
        """Tela 04 — detalhes da demanda com 11 abas e progresso (wf §6, ADR-0043)."""
        return FileResponse(_STATIC_DIR / "demanda-detalhe.html")

    # Sidebar de 16 seções (wf §2.4, ADR-0036) — ver docs/mapa-paginas.md para o
    # card FID que implementa o conteúdo de cada uma. Registradas como rotas
    # explícitas de nome fixo (mesmo padrão das 4 acima, geradas em laço só para
    # não repetir 16 funções quase idênticas) — NUNCA um path curinga: um
    # `/ui/{secao}` interceptaria `/ui/tokens.css`/`components.css`/`header.js`/
    # `sidebar.js` antes deles chegarem ao mount de `StaticFiles` abaixo.
    _SIDEBAR_SECOES = (
        "dashboard",
        "demandas",
        "esteira",
        "kanban",
        "agentes",
        "modelos",
        "documentos",
        "aprovacoes",
        "execucoes",
        "testes",
        "code-reviews",
        "implantacoes",
        "incidentes",
        "auditoria",
        "metricas",
        "configuracoes",
    )

    def _ui_secao_handler(nome_arquivo: str) -> Callable[[], FileResponse]:
        def handler() -> FileResponse:
            return FileResponse(_STATIC_DIR / nome_arquivo)

        return handler

    for _secao in _SIDEBAR_SECOES:
        app.add_api_route(
            f"/ui/{_secao}",
            _ui_secao_handler(f"{_secao}.html"),
            methods=["GET"],
            include_in_schema=False,
        )

    # Montagem de arquivos estáticos (CSS/JS/etc.), se houver.
    if _STATIC_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")

    return app


# Instância padrão para `uvicorn aso.api.app:app` (usa ASO_DATABASE_URL se definido).
app = create_app(build_service())
