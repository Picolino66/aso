"""check_drift — detecção determinística de drift docs↔código (só leitura)."""

from __future__ import annotations

from pathlib import Path

from aso.execution.docs_drift import check_drift
from aso.execution.docs_scaffold import write_scaffold


def _docs_base(root: Path, modules: list[str]) -> None:
    write_scaffold(root, modules)


def test_sem_docs_nao_acusa_drift(tmp_path: Path) -> None:
    rep = check_drift(tmp_path)
    assert rep.has_docs is False
    assert rep.has_drift is False


def test_docs_em_sincronia(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "app.py").write_text("x=1\n", encoding="utf-8")
    _docs_base(tmp_path, ["core"])
    # preenche o placeholder para não acusar unfilled
    feat = tmp_path / "docs" / "modules" / "core" / "core.md"
    feat.write_text(
        feat.read_text(encoding="utf-8").replace("_A preencher._", "conteúdo real"), "utf-8"
    )
    rep = check_drift(tmp_path)
    assert rep.has_docs is True
    assert rep.has_drift is False
    assert rep.undocumented_modules == []


def test_modulo_de_codigo_sem_doc(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "novo").mkdir()  # módulo novo, sem doc
    (tmp_path / "novo" / "b.py").write_text("", encoding="utf-8")
    _docs_base(tmp_path, ["core"])
    rep = check_drift(tmp_path)
    assert "novo" in rep.undocumented_modules
    assert rep.has_drift is True


def test_doc_orfa_de_modulo_removido(tmp_path: Path) -> None:
    _docs_base(tmp_path, ["antigo"])  # doc para módulo que não existe no código
    rep = check_drift(tmp_path)
    assert "antigo" in rep.orphan_module_docs
    assert rep.has_drift is True


def test_modulo_neutro_projeto_nao_e_orfao(tmp_path: Path) -> None:
    # scaffold de pasta vazia cria o módulo neutro "projeto" — não deve ser órfão.
    _docs_base(tmp_path, [])
    rep = check_drift(tmp_path)
    assert "projeto" not in rep.orphan_module_docs


def test_link_interno_quebrado(tmp_path: Path) -> None:
    _docs_base(tmp_path, ["core"])
    idx = tmp_path / "docs" / "index.md"
    idx.write_text(
        idx.read_text(encoding="utf-8") + "\n[quebrado](modules/inexistente/x.md)\n", "utf-8"
    )
    rep = check_drift(tmp_path)
    assert any("inexistente" in b for b in rep.broken_links)
    assert rep.has_drift is True


def test_placeholder_por_preencher_conta_como_drift(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "a.py").write_text("", encoding="utf-8")
    _docs_base(tmp_path, ["core"])  # feature com "_A preencher._"
    rep = check_drift(tmp_path)
    assert any("core.md" in f for f in rep.unfilled_features)
    assert rep.has_drift is True


def test_link_externo_e_ancora_nao_sao_drift(tmp_path: Path) -> None:
    _docs_base(tmp_path, ["core"])
    feat = tmp_path / "docs" / "modules" / "core" / "core.md"
    feat.write_text("# core\n\n[site](https://exemplo.com) [topo](#descrição)\n", encoding="utf-8")
    rep = check_drift(tmp_path)
    assert rep.broken_links == []
