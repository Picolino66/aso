"""Acesso somente leitura ao repositório para agentes de pergunta (ADR-0069, MEL-40).

Discovery e revisão perguntavam ao agente CLI numa pasta temporária **vazia**: o discovery só
recebia nomes de diretórios e o revisor só o diff, embora Claude Code e Codex saibam buscar e
ler código. Aqui a pergunta ganha um worktree **destacado e temporário** do ref relevante
(HEAD da pasta para discovery; branch da PR para revisão), com três camadas de proteção:

1. flag de somente leitura do próprio CLI quando conhecida (`comando_somente_leitura`);
2. worktree destacado fora da pasta do usuário — nenhuma branch é tocada por ele;
3. verificação depois da pergunta (`alteracoes`): árvore suja ou HEAD movido → a resposta é
   descartada (`EscritaNoRepositorio`), mesmo que o agente tenha respondido.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from aso.execution.worktree import lock_do_repositorio

SANDBOX_CODEX = "read-only"
PERMISSAO_CLAUDE = "plan"


@dataclass(frozen=True)
class AcessoAoRepositorio:
    """Onde o agente pode ler: a pasta do repositório e o ref (None = HEAD)."""

    caminho: str
    ref: str | None = None


class EscritaNoRepositorio(ValueError):
    """O agente alterou o worktree de leitura: a resposta não pode ser usada."""


def _git(cwd: str | Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise OSError(f"git {' '.join(args)} falhou: {proc.stderr.strip()[:300]}")
    return proc.stdout


def e_repositorio_git(caminho: str | None) -> bool:
    if not caminho or not Path(caminho).is_dir():
        return False
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=caminho,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def comando_somente_leitura(command: list[str]) -> list[str]:
    """Acrescenta (ou força) o modo de leitura dos CLIs conhecidos; outros ficam iguais."""
    nomes = [os.path.basename(token) for token in command]
    resultado = list(command)
    if "codex" in nomes:
        if "--sandbox" in resultado:
            i = resultado.index("--sandbox")
            if i + 1 < len(resultado):
                resultado[i + 1] = SANDBOX_CODEX
            else:
                resultado.append(SANDBOX_CODEX)
        else:
            pos = resultado.index("exec") + 1 if "exec" in resultado else len(resultado)
            resultado[pos:pos] = ["--sandbox", SANDBOX_CODEX]
    if "claude" in nomes:
        if "--permission-mode" in resultado:
            i = resultado.index("--permission-mode")
            if i + 1 < len(resultado):
                resultado[i + 1] = PERMISSAO_CLAUDE
        else:
            resultado.extend(["--permission-mode", PERMISSAO_CLAUDE])
    return resultado


@contextmanager
def worktree_de_leitura(acesso: AcessoAoRepositorio) -> Iterator[tuple[Path, str]]:
    """Cria um worktree destacado do ref num diretório temporário e o remove ao final.

    Devolve `(caminho, sha)`; o sha é o commit de partida usado por `alteracoes`."""
    sha = _git(acesso.caminho, "rev-parse", "--verify", f"{acesso.ref or 'HEAD'}^{{commit}}")
    sha = sha.strip()
    raiz = Path(tempfile.mkdtemp(prefix="aso-leitura-"))
    destino = raiz / "repo"
    with lock_do_repositorio(acesso.caminho):
        _git(acesso.caminho, "worktree", "add", "--detach", str(destino), sha)
    try:
        yield destino, sha
    finally:
        with lock_do_repositorio(acesso.caminho):
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(destino)],
                cwd=acesso.caminho,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "worktree", "prune"], cwd=acesso.caminho, capture_output=True, text=True
            )
        shutil.rmtree(raiz, ignore_errors=True)


def alteracoes(worktree: Path, sha: str) -> list[str]:
    """O que o agente mudou: arquivos (inclusive não rastreados) e HEAD movido."""
    mudancas = [linha for linha in _git(worktree, "status", "--porcelain").splitlines() if linha]
    if _git(worktree, "rev-parse", "HEAD").strip() != sha:
        mudancas.append("HEAD movido (commit durante a pergunta)")
    return mudancas


def caminho_existe(repositorio: str, relativo: str) -> bool:
    """`relativo` aponta para algo dentro do repositório? Recusa absolutos e `..`."""
    limpo = relativo.strip().strip("`'\"").removeprefix("./")
    if not limpo or os.path.isabs(limpo):
        return False
    base = Path(repositorio).resolve()
    alvo = (base / limpo.split(":")[0]).resolve()
    return alvo.is_relative_to(base) and alvo.exists()
