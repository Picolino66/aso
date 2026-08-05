"""Sugestão determinística de bateria por stack (§4.5, ADR-0022).

Sem agente: inspeção de arquivos do workspace. Nunca inventa comando de script que
não existe — pasta sem stack reconhecida devolve lista vazia.
"""

from __future__ import annotations

import json

from aso.control.validation import sugerir_bateria


def test_pyproject_sugere_bateria_python(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    nomes = {c.nome for c in sugerir_bateria(str(tmp_path))}
    assert nomes == {"lint", "formatacao", "tipos", "testes"}


def test_setup_cfg_tambem_sugere_bateria_python(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "setup.cfg").write_text("[metadata]\nname=x\n", encoding="utf-8")
    nomes = {c.nome for c in sugerir_bateria(str(tmp_path))}
    assert "testes" in nomes


def test_package_json_so_sugere_scripts_que_existem(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "jest", "build": "vite build"}}), encoding="utf-8"
    )
    checks = sugerir_bateria(str(tmp_path))
    nomes = {c.nome for c in checks}
    assert nomes == {"testes", "build"}  # "lint" não existe no package.json — não inventa
    comandos = {c.comando for c in checks}
    assert comandos == {"npm run test", "npm run build"}


def test_package_json_sem_scripts_nao_inventa_nada(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "package.json").write_text(json.dumps({}), encoding="utf-8")
    assert sugerir_bateria(str(tmp_path)) == []


def test_go_mod_sugere_bateria_go(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    nomes = {c.nome for c in sugerir_bateria(str(tmp_path))}
    assert nomes == {"vet", "build", "testes"}


def test_cargo_toml_sugere_bateria_rust(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")
    nomes = {c.nome for c in sugerir_bateria(str(tmp_path))}
    assert nomes == {"clippy", "formatacao", "testes"}


def test_workspace_vazio_devolve_lista_vazia_sem_inventar(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert sugerir_bateria(str(tmp_path)) == []


def test_sugestao_nao_grava_nada(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`sugerir_bateria` é puramente de leitura — não escreve no workspace."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    antes = sorted(p.name for p in tmp_path.iterdir())
    sugerir_bateria(str(tmp_path))
    depois = sorted(p.name for p in tmp_path.iterdir())
    assert antes == depois
