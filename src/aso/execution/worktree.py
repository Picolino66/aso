"""WorktreeManager — worktrees git isolados por card/agente (§26A.6).

Cada agente CLI que altera código roda em um worktree/branch isolado; o diff é
coletado antes de qualquer merge. Nunca opera na branch principal.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

# Operações de metadados do git (worktree add/remove, merge) tomam locks internos
# do repositório; serializamos aqui para permitir execução concorrente de candidatos.
_GIT_META_LOCK = threading.Lock()


class WorktreeError(RuntimeError):
    """Falha em operação de worktree git."""


class WorktreeManager:
    def __init__(self, base_repo: str) -> None:
        self.base = Path(base_repo)

    def _git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.base),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise WorktreeError(f"git {' '.join(args)} falhou: {result.stderr.strip()}")
        return result

    def create(self, name: str) -> tuple[Path, str]:
        """Cria um worktree em `.aso/worktrees/<name>` numa branch `aso/<name>`."""
        branch = f"aso/{name}"
        path = self.base / ".aso" / "worktrees" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with _GIT_META_LOCK:
            self._git("worktree", "add", "-b", branch, str(path), "HEAD")
        return path, branch

    def collect_diff(self, path: Path) -> str:
        """Coleta o diff (inclui arquivos novos) do worktree."""
        # `git add`/`commit` disputam lockfiles de ref/index com merge/worktree-add
        # concorrentes no mesmo repo base; serializamos para evitar falha espúria.
        with _GIT_META_LOCK:
            self._git("add", "-A", cwd=path)
            return self._git("diff", "--cached", cwd=path).stdout

    def commit(self, path: Path, message: str) -> None:
        """Faz commit do que já está staged no worktree (branch do card)."""
        with _GIT_META_LOCK:
            self._git("commit", "-m", message, cwd=path)

    def merge(self, branch: str, *, message: str = "aso: merge governado") -> None:
        """Faz merge governado da branch do card na branch atual do repositório base."""
        with _GIT_META_LOCK:
            self._git("merge", "--no-ff", "--no-edit", "-m", message, branch)

    def branch_diff(self, branch: str) -> str:
        """Retorna o diff de uma branch candidata contra HEAD, sem alterar o repositório."""
        with _GIT_META_LOCK:
            return self._git("diff", "HEAD..." + branch).stdout

    def run_on_branch(
        self, branch: str, command: list[str], *, timeout: float = 300.0
    ) -> tuple[bool, str]:
        """Executa a validação numa cópia temporária da branch da PR."""
        name = f"ci-{branch.rsplit('/', 1)[-1]}"
        path = self.base / ".aso" / "worktrees" / name
        with _GIT_META_LOCK:
            self._git("worktree", "add", "--detach", str(path), branch)
        try:
            result = subprocess.run(
                command, cwd=str(path), capture_output=True, text=True, timeout=timeout
            )
            detail = (result.stdout + result.stderr).strip()[-1000:]
            return result.returncode == 0, f"exit={result.returncode} {detail}".strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"falha ao executar CI: {exc}"
        finally:
            self.remove(path)

    def remove(self, path: Path) -> None:
        """Remove o worktree (best-effort)."""
        with _GIT_META_LOCK:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=str(self.base),
                capture_output=True,
                text=True,
            )
