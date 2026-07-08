"""(b) Múltiplos agentes CLI em paralelo por card + comparação de diffs (§26A.6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

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


def test_race_candidates_and_merge_recommended(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    # dois "agentes CLI" distintos gerando diffs diferentes, no mesmo repo base
    claude = CliAgentExecutionProvider(["bash", "-c", "echo a > sol_claude.py"], str(repo))
    codex = CliAgentExecutionProvider(
        ["bash", "-c", "printf 'a\\nb\\nc\\n' > sol_codex.py"], str(repo)
    )
    svc = OrchestrationService()
    orch = svc.create_orchestration("implementar no backend")
    card = svc.get_cards(orch.id)[0]

    comparison = svc.race_card(orch.id, card.id, [claude, codex])
    branches = {c["branch"] for c in comparison["candidates"]}
    assert len(branches) == 2  # dois candidatos isolados
    assert comparison["recommended_branch"]  # heurística escolheu um
    # candidatos tocam arquivos diferentes
    files = {tuple(c["files"]) for c in comparison["candidates"]}
    assert files == {("sol_claude.py",), ("sol_codex.py",)}

    # abre PR do candidato recomendado e faz merge governado (git real)
    svc._provider = claude  # noqa: SLF001 — provider com WorktreeManager para o merge
    pr = svc.open_pr(orch.id, card.id, branch=str(comparison["recommended_branch"]))
    svc.report_ci(orch.id, pr.id, "passed")
    svc.report_review(orch.id, pr.id, "approved")
    svc.merge_pr(orch.id, pr.id)
    # o recomendado (menor diff = sol_claude.py) foi mesclado na base
    assert (repo / "sol_claude.py").exists()
    assert not (repo / "sol_codex.py").exists()


def test_candidate_failure_is_isolated(tmp_path: Path) -> None:
    repo = tmp_path / "proj2"
    _init_repo(repo)
    good = CliAgentExecutionProvider(["bash", "-c", "echo ok > f.py"], str(repo))
    bad = CliAgentExecutionProvider(["bash", "-c", "echo x > g.py"], "/nao/existe/repo")
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    comparison = svc.race_card(orch.id, card.id, [good, bad])
    errs = [c for c in comparison["candidates"] if c["error"]]
    oks = [c for c in comparison["candidates"] if not c["error"]]
    assert len(errs) == 1 and len(oks) == 1  # falha de um não derruba o outro
    assert comparison["recommended_branch"] == oks[0]["branch"]
