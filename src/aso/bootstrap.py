"""Composition root — monta o OrchestrationService com os adapters corretos.

Seleciona aqui (e não no domínio) as implementações concretas:
- `ASO_DATABASE_URL`  -> SqlAlchemyOrchestrationRepository (Postgres/SQLite); senão in-memory.
- `ASO_CLI_COMMAND` + `ASO_TARGET_REPO` -> CliAgentExecutionProvider (worktrees); senão mock.
- `ASO_LLM_*` -> LlmExecutionProvider (planejamento); roteado por fase com o CLI (M5).
- `ASO_CANDIDATE_COMMANDS` + `ASO_TARGET_REPO` -> agentes CLI candidatos (§26A.6).
"""

from __future__ import annotations

import json
import os
import shlex

from aso.agents.executor import ExecutionProvider
from aso.control.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.execution.catalog import ExecutorCatalog, build_catalog_from_env
from aso.execution.cli_provider import CliAgentExecutionProvider
from aso.execution.llm_client import build_llm_client_from_env
from aso.execution.llm_provider import LlmExecutionProvider
from aso.execution.routing_provider import RoutingExecutionProvider
from aso.execution.settings_store import ExecutorSettingsStore


def build_service() -> OrchestrationService:
    url = os.environ.get("ASO_DATABASE_URL")
    repository = SqlAlchemyOrchestrationRepository(url) if url else None

    cli_command = os.environ.get("ASO_CLI_COMMAND")
    target_repo = os.environ.get("ASO_TARGET_REPO")
    coder: ExecutionProvider | None = None
    if cli_command and target_repo:
        coder = CliAgentExecutionProvider(shlex.split(cli_command), target_repo)

    llm = build_llm_client_from_env()
    planner: ExecutionProvider | None = LlmExecutionProvider(llm) if llm else None

    # Roteia por fase quando há os dois; senão usa o único disponível; senão mock.
    if planner and coder:
        provider: ExecutionProvider | None = RoutingExecutionProvider(planner=planner, coder=coder)
    else:
        provider = coder or planner

    # Catálogo: perfis persistidos na tela de config (arquivo) têm prioridade;
    # senão, deriva do ambiente (ASO_EXECUTORS + defaults). Chaves sempre no env.
    store = ExecutorSettingsStore()
    stored = store.load()
    catalog = ExecutorCatalog(stored) if stored else build_catalog_from_env()
    return OrchestrationService(
        provider=provider, repository=repository, catalog=catalog, executor_store=store
    )


def build_candidate_providers(target_repo: str | None = None) -> list[ExecutionProvider]:
    """Constrói os agentes CLI candidatos a partir do ambiente (§26A.6).

    `ASO_CANDIDATE_COMMANDS` (JSON) + a pasta alvo definem N agentes CLI que
    competem por card em worktrees isolados. Cada item pode ser:
    - string: o próprio comando (id derivado do índice, ex.: `cli_1`);
    - objeto: `{"id": "claude", "command": "claude -p"}`.
    `target_repo` (pasta da orquestração) tem prioridade sobre `ASO_TARGET_REPO`.
    Retorna lista vazia se não configurado (o endpoint de corrida responde 409).
    """
    target_repo = target_repo or os.environ.get("ASO_TARGET_REPO")
    raw = os.environ.get("ASO_CANDIDATE_COMMANDS")
    if not (target_repo and raw):
        return []
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
        return []
    providers: list[ExecutionProvider] = []
    for i, item in enumerate(spec):
        if isinstance(item, str):
            cid, cmd = f"cli_{i + 1}", item
        else:
            cid, cmd = str(item.get("id", f"cli_{i + 1}")), str(item["command"])
        providers.append(CliAgentExecutionProvider(shlex.split(cmd), target_repo, executor_id=cid))
    return providers
