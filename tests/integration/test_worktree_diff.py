"""Coleta do trabalho do card no worktree — com git real (§26A.6).

O caso que motivou estes testes: agentes CLI **commitam** o que produzem (o wrapper do
ASO pede "commits pequenos"), a árvore fica limpa e o `git diff --cached` puro saía
vazio — o runtime descartava trabalho real como se o agente não tivesse feito nada.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aso.agents.executor import AgentExecutionError
from aso.agents.models import AgentSpec
from aso.execution.cli_provider import CliAgentExecutionProvider
from aso.execution.worktree import WorktreeManager


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")


def _agent() -> AgentSpec:
    return AgentSpec(role="BackendDevelopmentAgent", context_sections=["engineering"])


def _task() -> dict[str, object]:
    return {"orchestration_id": "orch_x", "card_id": "card_x", "phase": "F5"}


def test_diff_inclui_o_que_o_agente_commitou(tmp_path: Path) -> None:
    """Agente bem-comportado que commita o próprio trabalho não pode dar 'diff vazio'."""
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    path, _branch = manager.create("agente-commita")
    (path / "calculadora.js").write_text("export const soma = (a, b) => a + b;\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "feat: calculadora")

    diff = manager.collect_diff(path)
    assert "calculadora.js" in diff
    assert "soma" in diff


def test_diff_inclui_trabalho_nao_commitado(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    path, _branch = manager.create("agente-nao-commita")
    (path / "novo.txt").write_text("conteúdo\n", encoding="utf-8")

    assert "novo.txt" in manager.collect_diff(path)


def test_diff_mistura_commitado_e_pendente(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    path, _branch = manager.create("agente-misto")
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "parte 1")
    (path / "b.txt").write_text("b\n", encoding="utf-8")

    diff = manager.collect_diff(path)
    assert "a.txt" in diff and "b.txt" in diff


def test_diff_vazio_quando_o_agente_nao_faz_nada(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    path, _branch = manager.create("agente-inerte")

    assert manager.collect_diff(path).strip() == ""


def test_diff_ignora_commits_que_o_repo_base_ganhou_depois(tmp_path: Path) -> None:
    """O card responde pelo que ELE fez, não pelo que o repo base andou em paralelo."""
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    path, _branch = manager.create("agente-paralelo")
    (path / "meu.txt").write_text("meu\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "trabalho do card")
    # Outro card mesclou algo na base enquanto este rodava.
    (repo / "de-outro.txt").write_text("outro\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "trabalho de outro card")

    diff = manager.collect_diff(path)
    assert "meu.txt" in diff
    assert "de-outro.txt" not in diff


def test_commit_e_no_op_com_arvore_limpa(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    path, branch = manager.create("ja-commitado")
    (path / "x.txt").write_text("x\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "do agente")

    manager.collect_diff(path)
    manager.commit(path, "aso: card")  # não pode explodir com "nothing to commit"
    assert "x.txt" in manager.branch_diff(branch)


def test_provider_aceita_agente_que_commita(tmp_path: Path) -> None:
    """Ponta a ponta no provider: CLI que commita gera AgentOutput, não AgentExecutionError."""
    repo = tmp_path / "proj"
    _init_repo(repo)
    comando = [
        "bash",
        "-c",
        "cat > /dev/null; echo 'const x = 1;' > mod.js; git add -A && git commit -q -m 'feat: mod'",
    ]
    provider = CliAgentExecutionProvider(comando, str(repo))
    saida = provider.execute(_agent(), _task())
    assert "mod.js" in saida.artifacts["diff"]
    assert saida.patches[0].content["diff_lines"] > 0


def test_provider_recusa_agente_que_nao_altera_nada(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    provider = CliAgentExecutionProvider(
        ["bash", "-c", "cat > /dev/null; echo 'só converso, não escrevo'"], str(repo)
    )
    try:
        provider.execute(_agent(), _task())
    except AgentExecutionError as erro:
        assert "diff vazio" in str(erro)
        assert "só converso" in str(erro)  # a fala do agente sobrevive ao erro
    else:  # pragma: no cover - falha explícita
        raise AssertionError("deveria ter recusado o diff vazio")


def test_changed_files_lista_so_os_caminhos(tmp_path: Path) -> None:
    """Tela 15 (wf §17.1, ADR-0048) — mesma comparação de `branch_diff`, só nomes."""
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    path, branch = manager.create("arquivos-alterados")
    (path / "novo.txt").write_text("novo\n", encoding="utf-8")
    (path / "README.md").write_text("mudou\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "do agente")

    manager.commit(path, "aso: card")
    arquivos = manager.changed_files(branch)
    assert set(arquivos) == {"novo.txt", "README.md"}


def test_changed_files_sem_mudanca_e_vazio(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    _, branch = manager.create("sem-mudanca")
    assert manager.changed_files(branch) == []


def test_commit_count_conta_commits_da_branch(tmp_path: Path) -> None:
    """Tela 18 (wf §20.1, ADR-0049)."""
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    path, branch = manager.create("dois-commits")
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "commit 1")
    (path / "b.txt").write_text("b\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "commit 2")

    assert manager.commit_count(branch) == 2


def test_commit_count_sem_mudanca_e_zero(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    _, branch = manager.create("sem-commit")
    assert manager.commit_count(branch) == 0


def test_line_stats_conta_adicoes_e_remocoes(tmp_path: Path) -> None:
    """Tela 18 (wf §20.1, ADR-0049)."""
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    path, branch = manager.create("linhas")
    (path / "README.md").write_text("linha 1\nlinha 2\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "altera readme")

    adicionadas, removidas = manager.line_stats(branch)
    assert adicionadas > 0
    assert removidas >= 0


def test_line_stats_sem_mudanca_e_zero(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    _, branch = manager.create("sem-linhas")
    assert manager.line_stats(branch) == (0, 0)
