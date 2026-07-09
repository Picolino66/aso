"""Workspace por orquestração: bootstrap git, docs-first e execução na pasta."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.workspace import WorkspaceAnalyzer, WorkspaceService


def _git_out(path: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True).stdout.strip()


def test_ensure_git_cria_repo_com_head(tmp_path: Path) -> None:
    ws = WorkspaceService()
    initialized = ws.ensure_git(tmp_path)
    assert initialized is True
    assert (tmp_path / ".git").exists()
    # HEAD válido (worktrees exigem) e .gitignore com .aso/worktrees/
    assert _git_out(tmp_path, "rev-parse", "--verify", "HEAD")
    assert ".aso/worktrees/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    # idempotente
    assert ws.ensure_git(tmp_path) is False


def _mock_catalog() -> ExecutorCatalog:
    return ExecutorCatalog([ExecutorProfile(name="mock", kind="mock", is_default=True)])


def test_analyze_folder_pasta_vazia_gera_scaffold(tmp_path: Path) -> None:
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("um projeto novo", target_path=str(tmp_path))
    out = svc.analyze_folder(orch.id)
    assert out["mode"] == "scaffold"
    assert out["git_initialized"] is True
    assert (tmp_path / "docs" / "index.md").is_file()
    assert (tmp_path / "docs" / "modules").is_dir()
    # commit determinístico do scaffold aconteceu
    assert "docs/index.md" in _git_out(tmp_path, "ls-files")
    rep = WorkspaceAnalyzer().analyze(tmp_path)
    assert rep.has_aso_docs is True


def test_analyze_folder_projeto_existente_com_agente_cli(tmp_path: Path) -> None:
    # Projeto existente (não vazio) já em git.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('oi')\n", encoding="utf-8")
    WorkspaceService().ensure_git(tmp_path)
    # Executor CLI fake que escreve docs/ no worktree (simula o agente documentando).
    cmd = (
        "mkdir -p docs/modules/src && "
        "printf '# docs\\n' > docs/index.md && "
        "printf '# src\\n' > docs/modules/src/src.md"
    )
    prof = ExecutorProfile(name="doccli", kind="cli", command=f'bash -c "{cmd}"', is_default=True)
    svc = OrchestrationService(catalog=ExecutorCatalog([prof]))
    orch = svc.create_orchestration("documente", target_path=str(tmp_path))
    out = svc.analyze_folder(orch.id, executor="doccli")
    assert out["mode"] == "agent"
    # o diff do agente foi mesclado na pasta (docs-first presente)
    assert (tmp_path / "docs" / "index.md").is_file()
    assert WorkspaceAnalyzer().analyze(tmp_path).has_aso_docs is True


def test_run_card_roda_na_pasta_da_orquestracao(tmp_path: Path) -> None:
    # Executor CLI fake (default) que cria um arquivo; sem provider explícito, run_card
    # deve resolver o provider atrelado à pasta desta orquestração (não um repo global).
    prof = ExecutorProfile(
        name="cli",
        kind="cli",
        command='bash -c "echo gerado > gerado.py"',
        is_default=True,
    )
    svc = OrchestrationService(catalog=ExecutorCatalog([prof]))
    orch = svc.create_orchestration("backend", target_path=str(tmp_path))
    WorkspaceService().ensure_git(tmp_path)
    card = svc.get_cards(orch.id)[0]
    results = svc.run_card(orch.id, card.id)  # provider=None → _provider_for(pasta)
    assert results and results[0].status.value == "applied"
    # o worktree/branch foi criado na pasta da orquestração
    assert "aso/" in _git_out(tmp_path, "branch")


def test_run_card_default_para_repo_global_sem_pasta(tmp_path: Path) -> None:
    # Sem target_path: cai no provider global do bootstrap (comportamento legado).
    from aso.execution.cli_provider import CliAgentExecutionProvider

    repo = tmp_path / "global"
    repo.mkdir()
    WorkspaceService().ensure_git(repo)
    provider = CliAgentExecutionProvider(["bash", "-c", "echo x > f.txt"], str(repo))
    svc = OrchestrationService(provider=provider, catalog=_mock_catalog())
    orch = svc.create_orchestration("backend")  # sem pasta
    card = svc.get_cards(orch.id)[0]
    results = svc.run_card(orch.id, card.id)
    assert results and results[0].status.value == "applied"
    assert "aso/" in _git_out(repo, "branch")
