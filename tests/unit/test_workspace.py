"""WorkspaceService (validação/list_dirs) e WorkspaceAnalyzer (só leitura)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.cli_provider import CliAgentExecutionProvider
from aso.execution.workspace import WorkspaceAnalyzer, WorkspaceService


def test_validate_rejects_missing_and_non_dir(tmp_path: Path) -> None:
    svc = WorkspaceService()
    with pytest.raises(ValueError, match="não existe"):
        svc.validate(str(tmp_path / "nao-existe"))
    f = tmp_path / "arquivo.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="não é uma pasta"):
        svc.validate(str(f))
    with pytest.raises(ValueError):
        svc.validate("")


def test_is_empty_ignora_caches(tmp_path: Path) -> None:
    svc = WorkspaceService()
    assert svc.is_empty(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "__pycache__").mkdir()
    assert svc.is_empty(tmp_path)  # só ignorados → ainda "vazia"
    (tmp_path / "main.py").write_text("print(1)", encoding="utf-8")
    assert not svc.is_empty(tmp_path)


def test_list_dirs_lista_so_diretorios(tmp_path: Path) -> None:
    (tmp_path / "sub1").mkdir()
    (tmp_path / "sub2").mkdir()
    (tmp_path / ".oculta").mkdir()
    (tmp_path / "arq.txt").write_text("x", encoding="utf-8")
    out = WorkspaceService().list_dirs(str(tmp_path))
    nomes = {d["name"] for d in out["dirs"]}  # type: ignore[union-attr]
    assert nomes == {"sub1", "sub2"}  # arquivos e ocultos fora
    assert out["path"] == str(tmp_path)
    assert out["parent"] == str(tmp_path.parent)


def test_list_dirs_inexistente_levanta() -> None:
    with pytest.raises(ValueError, match="não existe"):
        WorkspaceService().list_dirs("/caminho/que/nao/existe/zzz")


def test_analyzer_pasta_vazia(tmp_path: Path) -> None:
    rep = WorkspaceAnalyzer().analyze(tmp_path)
    assert rep.is_empty is True
    assert rep.is_git is False
    assert rep.has_aso_docs is False
    assert "docs/index.md" in rep.missing
    assert rep.detected_modules == []


def test_analyzer_projeto_sem_docs_detecta_modulos(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "node_modules").mkdir()  # ignorado
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    rep = WorkspaceAnalyzer().analyze(tmp_path)
    assert rep.is_empty is False
    assert rep.has_aso_docs is False
    assert set(rep.detected_modules) == {"src", "app"}


def test_analyzer_reconhece_docs_aso(tmp_path: Path) -> None:
    (tmp_path / "docs" / "modules").mkdir(parents=True)
    (tmp_path / "docs" / "index.md").write_text("# docs", encoding="utf-8")
    rep = WorkspaceAnalyzer().analyze(tmp_path)
    assert rep.has_aso_docs is True
    assert rep.missing == []


def test_catalog_build_usa_repo_override(tmp_path: Path) -> None:
    prof = ExecutorProfile(name="cli1", kind="cli", command="echo oi")
    cat = ExecutorCatalog([prof])
    provider = cat.build("cli1", repo_override=str(tmp_path))
    assert isinstance(provider, CliAgentExecutionProvider)
    assert provider.worktree.base == tmp_path


def test_catalog_build_cli_sem_repo_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASO_TARGET_REPO", raising=False)
    prof = ExecutorProfile(name="cli2", kind="cli", command="echo oi")
    cat = ExecutorCatalog([prof])
    with pytest.raises(ValueError, match="pasta da orquestração"):
        cat.build("cli2")  # sem repo_override e sem ASO_TARGET_REPO
