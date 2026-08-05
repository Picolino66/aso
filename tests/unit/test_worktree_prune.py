"""Worktrees órfãos após crash de processo (§1.4/§3.3 do plano7.md) — ADR-0027.

`WorktreeManager.create` normalmente é seguido de `remove` no `finally` de
`CliAgentExecutionProvider.execute` — um worktree só sobra em disco quando o processo
morreu no meio (`Ctrl-C`, OOM). Aqui simulamos exatamente isso: cria e NUNCA remove.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

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


def test_list_worktrees_encontra_o_que_ficou_para_tras(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    path, branch = manager.create("card-orfao")  # nunca chama remove — simula crash

    encontrados = manager.list_worktrees()

    assert any(w["path"] == str(path.resolve()) and w["branch"] == branch for w in encontrados)


def test_worktree_referenciado_por_card_ativo_nao_e_orfao(tmp_path: Path) -> None:
    """A marcação de órfão é responsabilidade do serviço (branches ativas), não do
    `WorktreeManager` — aqui confirmamos só que a listagem devolve o suficiente
    (`branch`) para o serviço decidir."""
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    _path, branch = manager.create("card-ativo")

    encontrados = manager.list_worktrees()

    ativo = next(w for w in encontrados if w["branch"] == branch)
    assert ativo["branch"] == branch  # o serviço cruza isto contra card.branch


def test_prune_remove_via_git_worktree_remove_nunca_rm_rf(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    path, _branch = manager.create("a-remover")
    assert path.exists()

    comandos: list[list[str]] = []
    original_run = subprocess.run

    def _run_espiao(args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(args, list) and args[:1] == ["git"]:
            comandos.append(args)
        return original_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _run_espiao)

    manager.prune([path])

    assert not path.exists()
    assert any(c[:3] == ["git", "worktree", "remove"] for c in comandos)
    assert any(c[:3] == ["git", "worktree", "prune"] for c in comandos)
    assert not any("rm" in c and "-rf" in c for c in comandos)


def test_prune_devolve_lista_do_que_seria_removido_antes(tmp_path: Path) -> None:
    """`list_worktrees` (chamado pelo serviço antes de `prune`) devolve tudo — quem
    filtra órfão é o serviço, e a lista completa é o que o `GET .../worktrees`
    expõe antes de qualquer remoção acontecer."""
    repo = tmp_path / "proj"
    _init_repo(repo)
    manager = WorktreeManager(str(repo))
    manager.create("um")
    manager.create("dois")

    antes = manager.list_worktrees()

    assert len(antes) == 2
