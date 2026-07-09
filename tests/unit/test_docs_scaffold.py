"""Scaffold determinístico de documentação docs-first (pt-BR, sem agente)."""

from __future__ import annotations

from pathlib import Path

from aso.execution.docs_scaffold import write_scaffold


def test_scaffold_empty_creates_index_and_modules_placeholder(tmp_path: Path) -> None:
    created = write_scaffold(tmp_path, modules=[])
    assert "docs/index.md" in created
    assert "docs/modules/.gitkeep" in created
    index = (tmp_path / "docs" / "index.md").read_text(encoding="utf-8")
    # Ponto de entrada docs-first, em pt-BR.
    assert "docs-first" in index.lower()
    assert "Leia este" in index
    assert (tmp_path / "docs" / "modules").is_dir()


def test_scaffold_with_modules_writes_feature_template_8_sections(tmp_path: Path) -> None:
    created = write_scaffold(tmp_path, modules=["api", "core"])
    assert "docs/modules/api/index.md" in created
    assert "docs/modules/api/api.md" in created
    feat = (tmp_path / "docs" / "modules" / "api" / "api.md").read_text(encoding="utf-8")
    for secao in (
        "## Descrição",
        "## Localização no código",
        "## Entrada",
        "## Saída",
        "## Dependências",
        "## Regras de negócio",
        "## Fluxo resumido",
        "## Possíveis erros",
    ):
        assert secao in feat
    # O índice lista os módulos com link.
    index = (tmp_path / "docs" / "index.md").read_text(encoding="utf-8")
    assert "modules/api/index.md" in index
    assert "modules/core/index.md" in index


def test_scaffold_does_not_overwrite_existing(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.md").write_text("MEU CONTEÚDO", encoding="utf-8")
    created = write_scaffold(tmp_path, modules=[])
    assert "docs/index.md" not in created  # não sobrescreve
    assert (tmp_path / "docs" / "index.md").read_text(encoding="utf-8") == "MEU CONTEÚDO"
