"""WorktreeManager — worktrees git isolados por card/agente (§26A.6).

Cada agente CLI que altera código roda em um worktree/branch isolado; o diff é
coletado antes de qualquer merge. Nunca opera na branch principal.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from aso.execution.branch_naming import worktree_dir_name

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

    def create(self, name: str, *, branch: str | None = None) -> tuple[Path, str]:
        """Cria um worktree em `.aso/worktrees/<dir>` na branch indicada.

        Sem `branch`, mantém o comportamento legado `aso/<name>`. Com `branch`, o nome
        vem do card (`feat/calculadora-basica-a1b2c3d4`, ADR-0014) e o diretório usa a
        versão achatada — barras criariam subdiretórios e um `remove` mais frágil.
        """
        branch = branch or f"aso/{name}"
        path = self.base / ".aso" / "worktrees" / worktree_dir_name(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _GIT_META_LOCK:
            self._git("worktree", "add", "-b", branch, str(path), "HEAD")
        return path, branch

    def collect_diff(self, path: Path) -> str:
        """Coleta **todo** o trabalho do card: commits do agente + o que ficou pendente.

        Comparar só o índice (`git diff --cached`) era um bug silencioso: agentes CLI
        costumam commitar o que fazem — o wrapper do ASO inclusive pede "commits
        pequenos" — e aí a árvore fica limpa, o diff sai vazio e o runtime descartava
        trabalho real como se o agente não tivesse feito nada. O diff certo é contra o
        **ponto de partida** da branch (merge-base com o HEAD do repo base), que cobre os
        dois casos e ignora commits que o repo base ganhou depois.
        """
        # `git add`/`commit` disputam lockfiles de ref/index com merge/worktree-add
        # concorrentes no mesmo repo base; serializamos para evitar falha espúria.
        with _GIT_META_LOCK:
            self._git("add", "-A", cwd=path)
            base_head = self._git("rev-parse", "HEAD").stdout.strip()
            origem = self._git("merge-base", "HEAD", base_head, cwd=path).stdout.strip()
            return self._git("diff", "--cached", origem, cwd=path).stdout

    def commit(self, path: Path, message: str) -> None:
        """Faz commit do que restou staged; no-op se o agente já commitou tudo."""
        with _GIT_META_LOCK:
            if not self._git("status", "--porcelain", cwd=path).stdout.strip():
                return  # árvore limpa: o trabalho já está nos commits do próprio agente
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
        path = self.base / ".aso" / "worktrees" / worktree_dir_name(f"ci-{branch}")
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

    def list_worktrees(self) -> list[dict[str, str]]:
        """Worktrees registrados sob `.aso/worktrees/` deste repositório (§3.3 do
        plano7.md, ADR-0027) — via `git worktree list --porcelain`, a mesma fonte de
        verdade que `scripts/reset.sh` usa, não uma varredura de diretório (que veria
        pasta órfã sem entrada git, ou entrada git sem pasta)."""
        raiz = str((self.base / ".aso" / "worktrees").resolve())
        with _GIT_META_LOCK:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=str(self.base),
                capture_output=True,
                text=True,
            )
        if result.returncode != 0:
            return []
        achados: list[dict[str, str]] = []
        atual: dict[str, str] = {}
        for linha in result.stdout.splitlines():
            if linha.startswith("worktree "):
                if atual:
                    achados.append(atual)
                atual = {"path": linha.removeprefix("worktree ").strip()}
            elif linha.startswith("branch "):
                atual["branch"] = linha.removeprefix("branch ").removeprefix("refs/heads/").strip()
        if atual:
            achados.append(atual)
        return [w for w in achados if w.get("path", "").startswith(raiz)]

    def prune(self, paths: list[Path]) -> None:
        """Remove os worktrees dados e limpa referências penduradas em
        `.git/worktrees` — nunca `rm -rf` (deixaria refs órfãs; o motivo pelo qual
        `scripts/reset.sh` também sempre passa pela porta do git)."""
        for path in paths:
            self.remove(path)
        with _GIT_META_LOCK:
            subprocess.run(
                ["git", "worktree", "prune"], cwd=str(self.base), capture_output=True, text=True
            )
