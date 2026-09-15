"""Composition root — monta o OrchestrationService com os adapters corretos.

Seleciona aqui (e não no domínio) as implementações concretas:
- `ASO_DATABASE_URL`  -> SqlAlchemyOrchestrationRepository (Postgres/SQLite); senão in-memory.
- executores: catálogo salvo (`.aso/executors.json`) ou semeado do ambiente (ADR-0076).
"""

from __future__ import annotations

import os

from aso.application.orchestration_service import OrchestrationService
from aso.db.repository import (
    SqlAlchemyAgentDefinitionRepository,
    SqlAlchemyAgentRunRepository,
    SqlAlchemyJobRepository,
    SqlAlchemyOrchestrationRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyRoutingRuleRepository,
)
from aso.execution.catalog import ExecutorCatalog, build_catalog_from_env
from aso.execution.jobs import InMemoryJobRepository, JobRepository
from aso.execution.settings_store import ExecutorSettingsStore


def build_service() -> OrchestrationService:
    # Produção: o schema é das migrations (Alembic, ADR-0068) — `create_all` só em testes.
    url = os.environ.get("ASO_DATABASE_URL")
    repository = SqlAlchemyOrchestrationRepository(url, create_schema=False) if url else None
    project_repository = SqlAlchemyProjectRepository(url, create_schema=False) if url else None
    routing_rule_repository = (
        SqlAlchemyRoutingRuleRepository(url, create_schema=False) if url else None
    )
    agent_definition_repository = (
        SqlAlchemyAgentDefinitionRepository(url, create_schema=False) if url else None
    )
    agent_run_repository = SqlAlchemyAgentRunRepository(url, create_schema=False) if url else None

    # Catálogo é a fonte única de executores (ADR-0076): perfis salvos na tela de config
    # (arquivo) valem; sem arquivo, o ambiente semeia o catálogo. Chaves sempre no env. Não há
    # mais provider global: a escolha por etapa sai do catálogo (`agent_assignments` + padrão).
    store = ExecutorSettingsStore()
    stored = store.load()
    catalog = ExecutorCatalog(stored) if stored else build_catalog_from_env()
    return OrchestrationService(
        repository=repository,
        project_repository=project_repository,
        routing_rule_repository=routing_rule_repository,
        agent_definition_repository=agent_definition_repository,
        agent_run_repository=agent_run_repository,
        catalog=catalog,
        executor_store=store,
    )


def build_job_repository() -> JobRepository:
    """Fila de jobs (ADR-0067): no banco quando há `ASO_DATABASE_URL`, senão em memória."""
    url = os.environ.get("ASO_DATABASE_URL")
    return SqlAlchemyJobRepository(url, create_schema=False) if url else InMemoryJobRepository()
