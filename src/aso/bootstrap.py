"""Composition root — monta o OrchestrationService com os adapters corretos.

Seleciona aqui (e não no domínio) as implementações concretas:
- `ASO_DATABASE_URL`  -> SqlAlchemyOrchestrationRepository (Postgres/SQLite); senão in-memory.
- `ASO_CLI_COMMAND` + `ASO_TARGET_REPO` -> CliAgentExecutionProvider (worktrees); senão mock.
"""

from __future__ import annotations

import os
import shlex

from aso.agents.executor import ExecutionProvider
from aso.control.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.execution.cli_provider import CliAgentExecutionProvider


def build_service() -> OrchestrationService:
    url = os.environ.get("ASO_DATABASE_URL")
    repository = SqlAlchemyOrchestrationRepository(url) if url else None

    provider: ExecutionProvider | None = None
    cli_command = os.environ.get("ASO_CLI_COMMAND")
    target_repo = os.environ.get("ASO_TARGET_REPO")
    if cli_command and target_repo:
        provider = CliAgentExecutionProvider(shlex.split(cli_command), target_repo)

    return OrchestrationService(provider=provider, repository=repository)
