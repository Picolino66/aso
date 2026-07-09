"""(a) CliAgentExecutionProvider: worktree isolado + diff real (§26.3/§26A.6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aso.agents.executor import AgentExecutionError
from aso.agents.models import AgentSpec
from aso.control.orchestration_service import OrchestrationService
from aso.execution.cli_provider import CliAgentExecutionProvider


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "README.md").write_text("base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "init")


def test_cli_provider_runs_in_worktree_and_collects_diff(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    # Comando fake que "edita código" no worktree (cria um arquivo).
    provider = CliAgentExecutionProvider(
        ["bash", "-c", "echo 'gerado pelo agente' > novo.py"], str(repo)
    )
    agent = AgentSpec(role="BackendDevelopmentAgent", context_sections=["engineering"])
    output = provider.execute(
        agent, {"orchestration_id": "o1", "card_id": "card_abc", "phase": "F5"}
    )

    assert output.executor_id == "cli_agent"
    assert "novo.py" in output.artifacts["diff"]
    assert output.patches[0].content["branch"].startswith("aso/BackendDevelopmentAgent-")
    assert output.patches[0].content["exit_code"] == 0
    # worktree removido (isolamento; nada vaza para a branch principal)
    wt = repo / ".aso" / "worktrees"
    assert not wt.exists() or not any(wt.iterdir())
    # a branch principal do repo permanece limpa
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
    )
    assert status.stdout.strip() == ""


def test_service_uses_cli_provider(tmp_path: Path) -> None:
    repo = tmp_path / "proj2"
    _init_repo(repo)
    provider = CliAgentExecutionProvider(["bash", "-c", "echo x > f.txt"], str(repo))
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration("implementar no backend")
    card = svc.get_cards(orch.id)[0]
    results = svc.run_card(orch.id, card.id)
    assert results and results[0].status.value == "applied"
    # o patch aplicado referencia o branch do worktree
    patches = svc.list_patches(orch.id)
    assert any("cli_" in p.target_path for p in patches)


@pytest.mark.parametrize("command", [["bash", "-c", "exit 7"], ["bash", "-c", "true"]])
def test_cli_provider_rejeita_falha_ou_diff_vazio(tmp_path: Path, command: list[str]) -> None:
    repo = tmp_path / "invalido"
    _init_repo(repo)
    provider = CliAgentExecutionProvider(command, str(repo))

    with pytest.raises(AgentExecutionError):
        provider.execute(AgentSpec(role="BackendDevelopmentAgent"), {"orchestration_id": "o"})
