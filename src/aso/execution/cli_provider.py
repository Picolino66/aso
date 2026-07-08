"""CliAgentExecutionProvider — executa um agente CLI real em worktree isolado (§26.3).

Cria um worktree/branch por card, roda o comando do agente CLI (ex.: `claude`, `codex`)
com o prompt via stdin, coleta o diff e retorna uma `AgentOutput` com um ContextPatch
descrevendo a alteração (branch + resumo do diff) — que o ContextBus valida/aplica.

O comando é injetável; nos testes usamos um comando fake que edita arquivos, exercitando
worktree + diff de verdade sem depender de um agente CLI instalado.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from aso.agents.models import AgentOutput, AgentSpec
from aso.execution.worktree import WorktreeManager
from aso.governance.models import ContextPatch
from aso.shared.ids import gen_id
from aso.shared.types import PatchType, Phase


class CliAgentExecutionProvider:
    """ExecutionProvider que roda um agente CLI em worktree isolado."""

    def __init__(
        self, command: list[str], base_repo: str, *, worktree: WorktreeManager | None = None
    ) -> None:
        self.id = "cli_agent"
        self.command = command
        self.worktree = worktree or WorktreeManager(base_repo)

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        name = f"{agent.role}-{gen_id()[:8]}"
        path, branch = self.worktree.create(name)
        try:
            proc = subprocess.run(
                self.command,
                cwd=str(path),
                input=json.dumps(task, ensure_ascii=False),
                capture_output=True,
                text=True,
            )
            diff = self.worktree.collect_diff(path)
            if diff.strip():
                self.worktree.commit(path, f"aso: {agent.role} ({task.get('card_id', '-')})")
        finally:
            self.worktree.remove(path)

        section = agent.context_sections[0] if agent.context_sections else "engineering"
        diff_lines = len(diff.splitlines())
        patch = ContextPatch(
            orchestration_id=str(task["orchestration_id"]),
            card_id=task.get("card_id"),
            agent=agent.role,
            phase=Phase(task.get("phase", Phase.F5)),
            patch_type=PatchType.UPDATE,
            target_path=f"{section}.cli_{agent.role}",
            content={"branch": branch, "diff_lines": diff_lines, "exit_code": proc.returncode},
            evidence=[f"worktree={name}", f"branch={branch}", f"exit={proc.returncode}"],
        )
        return AgentOutput(
            agent_role=agent.role,
            executor_id=self.id,
            summary=f"[cli] {agent.role} rodou em {branch} (diff: {diff_lines} linhas)",
            patches=[patch],
            artifacts={"branch": branch, "diff": diff, "stdout": proc.stdout[:2000]},
        )
