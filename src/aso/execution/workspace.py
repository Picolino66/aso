"""Workspace por orquestração — validação da pasta, bootstrap git e análise.

Cada orquestração trabalha numa pasta escolhida pelo usuário (o *workspace*). Este
módulo cuida de:

- `WorkspaceService.validate` — normaliza e valida o caminho (existe, é diretório);
- `WorkspaceService.ensure_git` — garante um repo git com HEAD (worktrees exigem HEAD);
- `WorkspaceService.list_dirs` — lista subdiretórios para o navegador de pastas da UI
  (só nomes/paths de diretórios, nunca conteúdo de arquivo);
- `WorkspaceAnalyzer.analyze` — inspeção determinística (git? vazia? docs IA-first?),
  base para decidir entre gerar scaffold ou pedir ao agente para documentar.

Tudo em pt-BR (regra de governança).
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel

# Diretórios ignorados ao detectar "módulos" e ao checar se a pasta está vazia.
_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".aso",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".idea",
        ".vscode",
        "target",
    }
)


class WorkspaceError(RuntimeError):
    """Falha em operação de workspace (git/bootstrap)."""


class WorkspaceReport(BaseModel):
    """Retrato determinístico de uma pasta de trabalho."""

    path: str
    is_git: bool
    is_empty: bool
    has_aso_docs: bool  # docs/index.md E docs/modules/ presentes
    missing: list[str]  # peças da estrutura docs-first que faltam
    detected_modules: list[str]  # diretórios de topo candidatos a virar docs/modules/<m>


class WorkspaceService:
    """Operações de sistema de arquivos e git sobre a pasta da orquestração."""

    def validate(self, path: str) -> Path:
        """Normaliza (`expanduser`) e valida: precisa existir e ser diretório."""
        if not path or not path.strip():
            raise ValueError("Informe o caminho da pasta de trabalho.")
        p = Path(path).expanduser()
        if not p.exists():
            raise ValueError(f"A pasta não existe: {p}")
        if not p.is_dir():
            raise ValueError(f"O caminho não é uma pasta: {p}")
        return p

    def is_empty(self, path: Path) -> bool:
        """A pasta está vazia para fins de projeto (ignora `.git`, caches etc.)?"""
        for entry in path.iterdir():
            if entry.name in _IGNORED_DIRS:
                continue
            return False
        return True

    def _git(self, path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(path),
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise WorkspaceError("Git indisponível no ambiente de execução.") from exc
        if result.returncode != 0:
            raise WorkspaceError(f"git {' '.join(args)} falhou: {result.stderr.strip()}")
        return result

    def is_git(self, path: Path) -> bool:
        return (path / ".git").exists()

    def commit_all(self, path: Path, message: str) -> bool:
        """Faz `git add -A` + commit em `path`. Retorna False se não havia mudança."""
        self._ensure_identity(path)
        self._git(path, "add", "-A")
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(path),
            capture_output=True,
            text=True,
        )
        if not status.stdout.strip():
            return False
        self._git(path, "commit", "-m", message)
        return True

    def ensure_git(self, path: Path) -> bool:
        """Garante um repo git com HEAD válido (worktrees exigem `HEAD`).

        Se ainda não há `.git`: `git init`, escreve `.gitignore` mínimo (para não
        versionar `.aso/worktrees/`), configura `user.name/email` locais se ausentes
        e faz um commit inicial `--allow-empty` (senão `git worktree add ... HEAD`
        quebra em repo sem commit). Retorna True se inicializou agora.
        """
        if self.is_git(path):
            self._ensure_head(path)
            return False
        self._git(path, "init")
        self._ensure_gitignore(path)
        self._ensure_identity(path)
        # add tolera pasta vazia; --allow-empty garante HEAD mesmo sem arquivos.
        self._git(path, "add", "-A")
        self._git(path, "commit", "--allow-empty", "-m", "aso: init do workspace")
        return True

    def _ensure_head(self, path: Path) -> None:
        """Repo já existe mas pode não ter commit (HEAD) — cria um se preciso."""
        probe = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=str(path),
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            self._ensure_identity(path)
            self._git(path, "commit", "--allow-empty", "-m", "aso: commit inicial (HEAD)")

    def _ensure_gitignore(self, path: Path) -> None:
        gi = path / ".gitignore"
        line = ".aso/worktrees/"
        if gi.exists():
            content = gi.read_text(encoding="utf-8")
            if line not in content:
                sep = "" if content.endswith("\n") or not content else "\n"
                gi.write_text(f"{content}{sep}{line}\n", encoding="utf-8")
        else:
            gi.write_text(f"# Gerado pelo ASO\n{line}\n", encoding="utf-8")

    def _ensure_identity(self, path: Path) -> None:
        """Garante user.name/email locais (senão o commit falha em ambientes limpos)."""
        for key, value in (("user.name", "ASO Runtime"), ("user.email", "aso@localhost")):
            probe = subprocess.run(
                ["git", "config", key],
                cwd=str(path),
                capture_output=True,
                text=True,
            )
            if probe.returncode != 0 or not probe.stdout.strip():
                self._git(path, "config", key, value)

    def list_dirs(self, path: str | None = None) -> dict[str, object]:
        """Lista subdiretórios de `path` (default: home) para o navegador de pastas.

        Retorna só nome+caminho de **diretórios** — nunca conteúdo de arquivo.
        Diretórios sem permissão de leitura são omitidos.
        """
        base = Path(path).expanduser() if path and path.strip() else Path.home()
        if not base.exists():
            raise ValueError(f"A pasta não existe: {base}")
        if not base.is_dir():
            raise ValueError(f"O caminho não é uma pasta: {base}")
        dirs: list[dict[str, str]] = []
        try:
            for entry in sorted(base.iterdir(), key=lambda e: e.name.lower()):
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir():
                        dirs.append({"name": entry.name, "path": str(entry)})
                except PermissionError:
                    continue
        except PermissionError as exc:
            raise ValueError(f"Sem permissão para ler: {base}") from exc
        parent = str(base.parent) if base.parent != base else None
        return {"path": str(base), "parent": parent, "dirs": dirs}

    def iter_files(self, path: str | Path) -> Iterator[Path]:
        """Enumera arquivos regulares elegíveis em ordem determinística e sem escrita.

        A pré-análise do console não pode inicializar git nem gerar documentação: ela
        apenas percorre a pasta escolhida para tornar a etapa visível ao usuário.
        Diretórios técnicos que não representam código do projeto são podados antes
        da descida, evitando custo e exposição desnecessária de caches/dependências.
        """
        root = path if isinstance(path, Path) else self.validate(path)

        def walk(directory: Path) -> Iterator[Path]:
            try:
                entries = sorted(directory.iterdir(), key=lambda entry: entry.name.lower())
            except PermissionError as exc:
                raise ValueError(f"Sem permissão para ler: {directory}") from exc

            for entry in entries:
                try:
                    # Não segue links: um atalho pode sair do workspace ou formar ciclo.
                    if entry.is_symlink():
                        continue
                    if entry.is_dir():
                        if entry.name in _IGNORED_DIRS:
                            continue
                        yield from walk(entry)
                    elif entry.is_file():
                        yield entry
                except PermissionError as exc:
                    raise ValueError(f"Sem permissão para ler: {entry}") from exc

        yield from walk(root)


class WorkspaceAnalyzer:
    """Análise determinística (só leitura) da pasta de trabalho."""

    def __init__(self, service: WorkspaceService | None = None) -> None:
        self._svc = service or WorkspaceService()

    def analyze(self, path: str | Path) -> WorkspaceReport:
        p = path if isinstance(path, Path) else self._svc.validate(str(path))
        is_git = self._svc.is_git(p)
        is_empty = self._svc.is_empty(p)
        docs_index = p / "docs" / "index.md"
        docs_modules = p / "docs" / "modules"
        has_aso_docs = docs_index.is_file() and docs_modules.is_dir()

        missing: list[str] = []
        if not docs_index.is_file():
            missing.append("docs/index.md")
        if not docs_modules.is_dir():
            missing.append("docs/modules/")

        detected_modules: list[str] = []
        for entry in sorted(p.iterdir(), key=lambda e: e.name.lower()):
            if entry.name.startswith(".") or entry.name in _IGNORED_DIRS:
                continue
            if entry.name in {"docs", "specs", "tasks", "agents", "skills", "adr"}:
                continue
            if entry.is_dir():
                detected_modules.append(entry.name)
        return WorkspaceReport(
            path=str(p),
            is_git=is_git,
            is_empty=is_empty,
            has_aso_docs=has_aso_docs,
            missing=missing,
            detected_modules=detected_modules,
        )
