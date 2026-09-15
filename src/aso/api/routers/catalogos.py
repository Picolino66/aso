"""Rotas de catálogos: executores, regras de roteamento, agentes e projetos.

Extraídas do `create_app` monolítico no MEL-32 passo 10 (ADR-0066).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from aso.agents.models import AgentDefinitionError
from aso.api.deps import ApiDeps, actor_de, raise_project_error
from aso.api.schemas import (
    AgentDefinitionBody,
    CreateProjectBody,
    ExecutorBody,
    RestoreProjectBody,
    RoutingRuleBody,
    RoutingRulePreviewBody,
    RoutingRuleReorderBody,
    UpdateProjectBody,
)
from aso.application.project_service import (
    ProjectConflictError,
    ProjectNotFoundError,
    ProjectValidationError,
)
from aso.control.routing_rules import RoutingRuleError
from aso.execution.codex_discovery import CodexDiscoveryError


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()
    svc = deps.svc

    @router.get("/v1/executors")
    def list_executors() -> Any:
        """Executores disponíveis para escolha por etapa (nome, tipo, modelo, esforços)."""
        return svc.list_executors()

    @router.post("/v1/executors", status_code=201)
    def upsert_executor(body: ExecutorBody) -> Any:
        """Cria/atualiza um perfil de executor (tela de configurações). Chave fica no env."""
        from aso.execution.catalog import ExecutorProfile

        return svc.save_executor(ExecutorProfile(**body.model_dump()))

    @router.post("/v1/executors/sync")
    def sync_executors() -> Any:
        """Sincroniza os modelos anunciados pelo Codex efetivo do processo da API."""
        try:
            return svc.sync_codex_executors()
        except CodexDiscoveryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.delete("/v1/executors/{name}")
    def delete_executor(name: str) -> Any:
        """Remove um perfil de executor (exceto 'mock')."""
        try:
            return svc.delete_executor(name)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    # ---- Regras de roteamento (§33, ADR-0028) --------------------------------

    @router.get("/v1/routing-rules")
    def list_routing_rules(only_active: bool = Query(default=False)) -> Any:
        """Regras SE/ENTÃO avaliadas antes da heurística do decision engine."""
        return svc.list_routing_rules(only_active=only_active)

    @router.post("/v1/routing-rules", status_code=201)
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
                actor=actor_de(request),
            )
        except RoutingRuleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @router.post("/v1/routing-rules/preview")
    def preview_routing_rule(body: RoutingRulePreviewBody) -> Any:
        """Quais demandas já existentes casariam com esta regra ainda não salva
        (Tela 31, wf §33.2, ADR-0042)."""
        try:
            return svc.preview_routing_rule(condicoes=body.condicoes, acao=body.acao)
        except RoutingRuleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @router.put("/v1/routing-rules/reorder")
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

    @router.put("/v1/routing-rules/{rule_id}")
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

    @router.delete("/v1/routing-rules/{rule_id}")
    def delete_routing_rule(rule_id: str) -> Any:
        """Remove uma regra de roteamento (ação crítica — exige papel admin)."""
        try:
            svc.delete_routing_rule(rule_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return {"deleted": rule_id}

    # ---- Catálogo de agentes (Tela 30, wf §32, ADR-0053) ---------------------

    @router.get("/v1/agent-definitions")
    def list_agent_definitions(only_active: bool = Query(default=False)) -> Any:
        """13 campos por agente — fonte de verdade das permissões reais."""
        return svc.list_agent_definitions(only_active=only_active)

    @router.get("/v1/agent-definitions/roles")
    def get_agent_real_roles() -> Any:
        """Papéis reais do AgentRegistry, para vincular uma definição só a um
        `role` que de fato existe — registrada ANTES de `/{definition_id}`
        (segmento literal, mesmo cuidado de `routing-rules/reorder`, ADR-0042)."""
        return svc.get_agent_real_roles()

    @router.get("/v1/agent-definitions/{definition_id}")
    def get_agent_definition(definition_id: str) -> Any:
        try:
            return svc.get_agent_definition(definition_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.post("/v1/agent-definitions", status_code=201)
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
                actor=actor_de(request),
            )
        except AgentDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @router.put("/v1/agent-definitions/{definition_id}")
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

    @router.delete("/v1/agent-definitions/{definition_id}")
    def delete_agent_definition(definition_id: str) -> Any:
        """Remove uma definição de agente (ação crítica — exige papel admin)."""
        try:
            svc.delete_agent_definition(definition_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return {"deleted": definition_id}

    # ---- Projetos (agrupadores do Kanban Macro) ------------------------------

    @router.get("/v1/projects")
    def list_projects(include_archived: bool = Query(default=False)) -> Any:
        return svc.list_projects(include_archived=include_archived)

    @router.post("/v1/projects", status_code=201)
    def create_project(body: CreateProjectBody, request: Request) -> Any:
        try:
            return svc.create_project(
                name=body.name,
                description=body.description,
                target_path=body.target_path,
                actor=actor_de(request),
            )
        except (ProjectValidationError, ProjectConflictError) as exc:
            raise_project_error(exc)

    @router.get("/v1/projects/{project_id}")
    def get_project(project_id: str) -> Any:
        try:
            return svc.get_project(project_id)
        except ProjectNotFoundError as exc:
            raise_project_error(exc)

    @router.patch("/v1/projects/{project_id}")
    @router.put("/v1/projects/{project_id}")
    def update_project(project_id: str, body: UpdateProjectBody, request: Request) -> Any:
        try:
            return svc.update_project(
                project_id,
                name=body.name,
                description=body.description,
                target_path=body.target_path,
                actor=actor_de(request),
            )
        except (ProjectNotFoundError, ProjectValidationError, ProjectConflictError) as exc:
            raise_project_error(exc)

    @router.delete("/v1/projects/{project_id}", status_code=200)
    def archive_project(project_id: str, request: Request) -> Any:
        """Arquiva metadados sem apagar orquestrações nem rastreabilidade."""
        try:
            return svc.archive_project(project_id, actor=actor_de(request))
        except ProjectNotFoundError as exc:
            raise_project_error(exc)

    @router.post("/v1/projects/{project_id}/restore")
    def restore_project(project_id: str, body: RestoreProjectBody, request: Request) -> Any:
        try:
            return svc.restore_project(
                project_id, actor=actor_de(request), target_path=body.target_path
            )
        except (ProjectNotFoundError, ProjectValidationError, ProjectConflictError) as exc:
            raise_project_error(exc)

    @router.get("/v1/projects/{project_id}/events")
    def project_events(project_id: str) -> Any:
        try:
            return svc.project_events(project_id)
        except ProjectNotFoundError as exc:
            raise_project_error(exc)

    return router
