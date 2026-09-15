"""MEL-51 — escritas git serializadas por repositório, não por processo."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from aso.execution.worktree import WorktreeManager, lock_do_repositorio


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


def _medir_worktree_add(
    monkeypatch: pytest.MonkeyPatch, bases: list[Path]
) -> list[tuple[float, float]]:
    """Cria um worktree em cada base, em threads, com o `git worktree add` lento."""
    original = WorktreeManager._git
    intervalos: list[tuple[float, float]] = []
    guarda = threading.Lock()

    def _git_lento(self: WorktreeManager, *args: str, cwd: Path | None = None) -> Any:
        if args[:2] == ("worktree", "add"):
            inicio = time.monotonic()
            time.sleep(0.4)
            resultado = original(self, *args, cwd=cwd)
            with guarda:
                intervalos.append((inicio, time.monotonic()))
            return resultado
        return original(self, *args, cwd=cwd)

    monkeypatch.setattr(WorktreeManager, "_git", _git_lento)
    threads = [
        threading.Thread(target=WorktreeManager(str(base)).create, args=(f"card-{i}",))
        for i, base in enumerate(bases)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    return intervalos


def _sobrepoem(intervalos: list[tuple[float, float]]) -> bool:
    (a_ini, a_fim), (b_ini, b_fim) = intervalos
    return max(a_ini, b_ini) < min(a_fim, b_fim)


def test_repositorios_distintos_escrevem_em_paralelo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bases = [_repo(tmp_path / "a"), _repo(tmp_path / "b")]
    intervalos = _medir_worktree_add(monkeypatch, bases)
    assert len(intervalos) == 2 and _sobrepoem(intervalos)


def test_mesmo_repositorio_continua_serializado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _repo(tmp_path / "a")
    intervalos = _medir_worktree_add(monkeypatch, [base, base])
    assert len(intervalos) == 2 and not _sobrepoem(intervalos)


def test_lock_e_por_caminho_resolvido(tmp_path: Path) -> None:
    a = _repo(tmp_path / "a")
    b = _repo(tmp_path / "b")
    assert lock_do_repositorio(a) is lock_do_repositorio(f"{a}/.")
    assert lock_do_repositorio(a) is not lock_do_repositorio(b)


def test_leitura_nao_espera_escrita_do_mesmo_repositorio(tmp_path: Path) -> None:
    base = _repo(tmp_path / "a")
    manager = WorktreeManager(str(base))
    _, branch = manager.create("card-leitura")
    with lock_do_repositorio(base):  # outra operação escrevendo
        inicio = time.monotonic()
        assert manager.changed_files(branch) == []
        assert manager.commit_count(branch) == 0
        assert time.monotonic() - inicio < 5
