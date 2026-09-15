"""`CatalogService` — projetos, executores, regras de roteamento e catálogo de agentes (ADR-0066).

MEL-32, passo 9: configuração global do runtime (ADR-0010, ADR-0011, ADR-0028, ADR-0053),
separada do fluxo das orquestrações.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from aso.application.agent_catalog_service import AgentCatalogService
from aso.application.project_service import ProjectService
from aso.application.routing_rule_service import RoutingRuleService
from aso.control.models import Project, ProjectEvent
from aso.control.routing_rules import (
    RoutingAction,
    RoutingCondition,
    RoutingRule,
    avaliar_regras,
    contexto_de_demand_brief,
    validar_regra,
)
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile, managed_codex_profiles
from aso.execution.codex_discovery import CodexDiscoveryError, discover_codex
from aso.execution.settings_store import ExecutorSettingsStore
from aso.shared.cache import TTLCache


class CatalogService:
    """Catálogos globais do runtime: projetos, executores, regras de roteamento e agentes."""

    def __init__(
        self,
        *,
        projects: ProjectService,
        routing_rules: RoutingRuleService,
        agent_catalog: AgentCatalogService,
        executor_store: ExecutorSettingsStore | None,
        catalogo_get: Callable[[], ExecutorCatalog | None],
        catalogo_set: Callable[[ExecutorCatalog], None],
        list_all: Callable[..., list[Any]],
    ) -> None:
        self._projects = projects
        self._routing_rules = routing_rules
        self._agent_catalog = agent_catalog
        self._executor_store = executor_store
        self._catalogo_get = catalogo_get
        self._catalogo_set = catalogo_set
        self._list_all = list_all
        # Descoberta de capacidades do Codex é cara: cache curto sob lock próprio.
        self._codex_cache = TTLCache(ttl_seconds=60.0)
        self._codex_lock = threading.Lock()

    # O catálogo de executores pertence à façade (outros serviços o leem a cada uso).
    @property
    def _catalog(self) -> ExecutorCatalog | None:
        return self._catalogo_get()

    @_catalog.setter
    def _catalog(self, valor: ExecutorCatalog) -> None:
        self._catalogo_set(valor)

    def list_all(self, *args: Any, **kwargs: Any) -> list[Any]:
        return self._list_all(*args, **kwargs)

    # --------------------------------------------------------- catálogo de projetos
    def create_project(
        self, *, name: str, description: str, target_path: str, actor: str
    ) -> Project:
        return self._projects.create(
            name=name, description=description, target_path=target_path, actor=actor
        )

    def list_projects(self, *, include_archived: bool = False) -> list[Project]:
        return self._projects.list_projects(include_archived=include_archived)

    def get_project(self, project_id: str) -> Project:
        return self._projects.get(project_id)

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None,
        description: str | None,
        target_path: str | None,
        actor: str,
    ) -> Project:
        return self._projects.update(
            project_id,
            name=name,
            description=description,
            target_path=target_path,
            actor=actor,
        )

    def archive_project(self, project_id: str, *, actor: str) -> Project:
        return self._projects.archive(project_id, actor=actor)

    def restore_project(
        self, project_id: str, *, actor: str, target_path: str | None = None
    ) -> Project:
        return self._projects.restore(project_id, actor=actor, target_path=target_path)

    def project_events(self, project_id: str) -> list[ProjectEvent]:
        return self._projects.events(project_id)

    def _catalogo_garantido(self) -> ExecutorCatalog:
        catalogo = self._catalog
        if catalogo is None:
            catalogo = ExecutorCatalog()
            self._catalog = catalogo
        return catalogo

    def list_executors(self) -> list[dict[str, object]]:
        """Executores disponíveis (para escolha por etapa na UI/API)."""
        return self._catalog.entries() if self._catalog is not None else []

    def sync_codex_executors(self) -> list[dict[str, object]]:
        """Descobre o Codex efetivo e substitui somente os perfis gerenciados."""
        catalogo = self._catalogo_garantido()
        with self._codex_lock:
            try:
                capabilities = discover_codex()
            except CodexDiscoveryError:
                raise
            catalogo.replace_managed_codex(managed_codex_profiles(capabilities))
            self._codex_cache.set("capabilities", capabilities)
            if self._executor_store is not None:
                self._executor_store.save(catalogo.profiles())
        return catalogo.entries()

    def save_executor(self, profile: ExecutorProfile) -> list[dict[str, object]]:
        """Cria/atualiza um perfil de executor (tela de configurações) e persiste."""
        catalogo = self._catalogo_garantido()
        catalogo.upsert(profile)
        if self._executor_store is not None:
            self._executor_store.save(catalogo.profiles())
        return catalogo.entries()

    def delete_executor(self, name: str) -> list[dict[str, object]]:
        """Remove um perfil de executor (exceto 'mock') e persiste."""
        if self._catalog is None:
            return []
        self._catalog.remove(name)
        if self._executor_store is not None:
            self._executor_store.save(self._catalog.profiles())
        return self._catalog.entries()

    def list_routing_rules(self, *, only_active: bool = False) -> list[dict[str, object]]:
        return [
            r.model_dump(mode="json")
            for r in self._routing_rules.list_rules(only_active=only_active)
        ]

    def create_routing_rule(
        self,
        *,
        nome: str,
        descricao: str,
        ativa: bool,
        precedencia: int,
        condicoes: list[RoutingCondition],
        acao: RoutingAction,
        actor: str,
    ) -> dict[str, object]:
        rule = self._routing_rules.create(
            nome=nome,
            descricao=descricao,
            ativa=ativa,
            precedencia=precedencia,
            condicoes=condicoes,
            acao=acao,
            actor=actor,
        )
        return rule.model_dump(mode="json")

    def update_routing_rule(
        self,
        rule_id: str,
        *,
        nome: str,
        descricao: str,
        ativa: bool,
        precedencia: int,
        condicoes: list[RoutingCondition],
        acao: RoutingAction,
    ) -> dict[str, object]:
        rule = self._routing_rules.update(
            rule_id,
            nome=nome,
            descricao=descricao,
            ativa=ativa,
            precedencia=precedencia,
            condicoes=condicoes,
            acao=acao,
        )
        return rule.model_dump(mode="json")

    def delete_routing_rule(self, rule_id: str) -> None:
        self._routing_rules.delete(rule_id)

    def reorder_routing_rules(self, ordem: list[str]) -> list[dict[str, object]]:
        """Tela 31 (wf §33, ADR-0042): reordena por arrasta-e-solta, reatribuindo
        `precedencia` a partir da ordem visual recebida."""
        return [r.model_dump(mode="json") for r in self._routing_rules.reorder(ordem)]

    def preview_routing_rule(
        self, *, condicoes: list[RoutingCondition], acao: RoutingAction | None = None
    ) -> list[dict[str, object]]:
        """Tela 31 (wf §33.2, ADR-0042): quais demandas JÁ EXISTENTES casariam com
        esta regra ainda não salva — reaproveita `avaliar_regras` (motor puro do
        FID-01/ADR-0028), sem duplicar a lógica de match no frontend. Varredura
        completa de `list_all()` (leve, sem hidratar bundle): mesma filosofia
        dev-scale já aceita em `header_summary`/`search` (ADR-0035)."""
        regra_candidata = RoutingRule(
            nome="__preview__", condicoes=condicoes, acao=acao or RoutingAction()
        )
        validar_regra(regra_candidata)
        casam: list[dict[str, object]] = []
        for o in self.list_all():
            if not o.demand_brief:
                continue
            brief = DemandBrief.model_validate(o.demand_brief)
            contexto = contexto_de_demand_brief(brief)
            if avaliar_regras([regra_candidata], contexto) is not None:
                casam.append(
                    {
                        "orchestration_id": o.id,
                        "user_request": o.user_request,
                        "tipo": brief.tipo,
                        "risco": brief.risco.value,
                        "complexidade": brief.complexidade,
                    }
                )
        return casam

    def list_agent_definitions(self, *, only_active: bool = False) -> list[dict[str, object]]:
        return [
            d.model_dump(mode="json")
            for d in self._agent_catalog.list_definitions(only_active=only_active)
        ]

    def get_agent_definition(self, definition_id: str) -> dict[str, object]:
        return self._agent_catalog.get(definition_id).model_dump(mode="json")

    def create_agent_definition(
        self,
        *,
        nome: str,
        tipo: str = "",
        funcao: str = "",
        plataforma: str = "",
        role: str = "",
        modelos_permitidos: list[str] | None = None,
        efforts_permitidos: list[str] | None = None,
        ferramentas: list[str] | None = None,
        permissoes: list[str] | None = None,
        projetos: list[str] | None = None,
        categorias_tarefa: list[str] | None = None,
        limite_custo_usd: float | None = None,
        limite_tentativas: int | None = None,
        exige_supervisao: bool = False,
        ativo: bool = True,
        actor: str,
    ) -> dict[str, object]:
        definicao = self._agent_catalog.create(
            nome=nome,
            tipo=tipo,
            funcao=funcao,
            plataforma=plataforma,
            role=role,
            modelos_permitidos=modelos_permitidos,
            efforts_permitidos=efforts_permitidos,
            ferramentas=ferramentas,
            permissoes=permissoes,
            projetos=projetos,
            categorias_tarefa=categorias_tarefa,
            limite_custo_usd=limite_custo_usd,
            limite_tentativas=limite_tentativas,
            exige_supervisao=exige_supervisao,
            ativo=ativo,
            actor=actor,
        )
        return definicao.model_dump(mode="json")

    def update_agent_definition(
        self,
        definition_id: str,
        *,
        nome: str,
        tipo: str = "",
        funcao: str = "",
        plataforma: str = "",
        role: str = "",
        modelos_permitidos: list[str] | None = None,
        efforts_permitidos: list[str] | None = None,
        ferramentas: list[str] | None = None,
        permissoes: list[str] | None = None,
        projetos: list[str] | None = None,
        categorias_tarefa: list[str] | None = None,
        limite_custo_usd: float | None = None,
        limite_tentativas: int | None = None,
        exige_supervisao: bool = False,
        ativo: bool = True,
    ) -> dict[str, object]:
        definicao = self._agent_catalog.update(
            definition_id,
            nome=nome,
            tipo=tipo,
            funcao=funcao,
            plataforma=plataforma,
            role=role,
            modelos_permitidos=modelos_permitidos,
            efforts_permitidos=efforts_permitidos,
            ferramentas=ferramentas,
            permissoes=permissoes,
            projetos=projetos,
            categorias_tarefa=categorias_tarefa,
            limite_custo_usd=limite_custo_usd,
            limite_tentativas=limite_tentativas,
            exige_supervisao=exige_supervisao,
            ativo=ativo,
        )
        return definicao.model_dump(mode="json")

    def delete_agent_definition(self, definition_id: str) -> None:
        self._agent_catalog.delete(definition_id)

    def _validate_executor(self, name: str, effort: str | None = None) -> ExecutorProfile:
        if self._catalog is None:
            raise ValueError("Catálogo de executores não configurado.")
        profile = self._catalog.validate(name, effort)
        if profile.managed_by != "codex":
            return profile
        with self._codex_lock:
            capabilities = self._codex_cache.get("capabilities")
            if capabilities is None:
                try:
                    capabilities = discover_codex()
                except CodexDiscoveryError as exc:
                    raise ValueError(f"Não foi possível validar o executor Codex: {exc}") from exc
                self._codex_cache.set("capabilities", capabilities)
        models = {model.model: model for model in capabilities.models}
        model = (
            models.get(profile.model)
            if profile.model
            else next(
                (candidate for candidate in capabilities.models if candidate.is_default),
                capabilities.models[0],
            )
        )
        if profile.model and model is None:
            raise ValueError(
                f"Executor '{name}' indisponível: modelo não anunciado pelo Codex atual."
            )
        if model is not None and (effort or profile.effort) not in model.supported_efforts:
            raise ValueError(
                f"Esforço '{effort or profile.effort}' não é aceito por {model.model}; "
                f"use: {', '.join(model.supported_efforts)}."
            )
        return profile
