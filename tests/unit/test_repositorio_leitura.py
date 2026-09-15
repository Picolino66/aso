"""MEL-40 — worktree de leitura, flags de somente leitura e caminhos (ADR-0069)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aso.control.review import _pedido, system_de_revisao
from aso.execution.repositorio_leitura import (
    AcessoAoRepositorio,
    alteracoes,
    caminho_existe,
    comando_somente_leitura,
    e_repositorio_git,
    worktree_de_leitura,
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _git(path, *args)
    (path / "src").mkdir()
    (path / "src" / "frete.py").write_text("TAXA = 0.1\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


def test_codex_gerenciado_troca_workspace_write_por_read_only() -> None:
    cmd = [
        "/app/scripts/aso-agent-wrapper.sh",
        "/usr/bin/codex",
        "exec",
        "--sandbox",
        "workspace-write",
        "-m",
        "gpt",
    ]
    assert comando_somente_leitura(cmd)[4] == "read-only"


def test_codex_sem_sandbox_recebe_read_only_depois_do_exec() -> None:
    assert comando_somente_leitura(["codex", "exec", "--json"]) == [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--json",
    ]


def test_claude_recebe_modo_de_permissao_sem_edicao() -> None:
    assert comando_somente_leitura(["claude", "-p"]) == [
        "claude",
        "-p",
        "--permission-mode",
        "plan",
    ]
    forcado = comando_somente_leitura(["claude", "-p", "--permission-mode", "acceptEdits"])
    assert forcado[-1] == "plan"


def test_cli_desconhecido_fica_igual() -> None:
    assert comando_somente_leitura(["aider", "--yes"]) == ["aider", "--yes"]


def test_caminho_existe_recusa_absoluto_travessia_e_inexistente(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    assert caminho_existe(str(repo), "src/frete.py")
    assert caminho_existe(str(repo), "./src")
    assert caminho_existe(str(repo), "src/frete.py:1")
    assert not caminho_existe(str(repo), "src/inexistente.py")
    assert not caminho_existe(str(repo), "/etc/passwd")
    (tmp_path / "fora.txt").write_text("fora do repositório")
    assert not caminho_existe(str(repo), "../fora.txt")
    assert not caminho_existe(str(repo), "")


def test_worktree_de_leitura_e_removido_e_detecta_escrita_e_commit(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    assert e_repositorio_git(str(repo)) and not e_repositorio_git(str(tmp_path))
    head = _git(repo, "rev-parse", "HEAD")
    with worktree_de_leitura(AcessoAoRepositorio(caminho=str(repo))) as (pasta, sha):
        assert sha == head and (pasta / "src" / "frete.py").exists()
        assert alteracoes(pasta, sha) == []
        (pasta / "novo.txt").write_text("x")
        assert any("novo.txt" in m for m in alteracoes(pasta, sha))
        _git(pasta, "add", "-A")
        _git(pasta, "commit", "-q", "-m", "intruso")
        assert any("HEAD movido" in m for m in alteracoes(pasta, sha))
    assert not pasta.exists()
    assert len(_git(repo, "worktree", "list").splitlines()) == 1
    assert _git(repo, "rev-parse", "HEAD") == head  # branch base intacta
    assert _git(repo, "status", "--porcelain") == ""


def test_pedido_de_revisao_leva_spec_criterios_adrs_e_ci() -> None:
    pedido = _pedido(
        "diff --git a/x b/x",
        "",
        "Corrigir frete",
        "descrição",
        ["frete grátis acima de 100"],
        ["regressão no checkout"],
        item_de_spec={"titulo": "Corrigir frete", "descricao": "regra nova"},
        adrs=[("ADR-0003", "Cálculo no backend", "o cálculo fica no serviço")],
        saida_ci="status: failed (origem: executada)\n1 teste falhou",
    )
    assert "Critérios de aceite: frete grátis acima de 100" in pedido
    assert "Item de especificação de origem" in pedido and "regra nova" in pedido
    assert "ADR relacionada ADR-0003 — Cálculo no backend" in pedido
    assert "Última execução da CI" in pedido and "1 teste falhou" in pedido
    assert "diff --git" in pedido


def test_prompt_do_revisor_muda_com_acesso_ao_repositorio() -> None:
    assert "NÃO tem acesso ao restante do repositório" in system_de_revisao(com_repositorio=False)
    com = system_de_revisao(com_repositorio=True)
    assert "checkout SOMENTE LEITURA" in com and "NÃO tem acesso" not in com
