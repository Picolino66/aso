"""Perfis Codex gerenciados e aplicação dinâmica de esforço."""

from __future__ import annotations

from pathlib import Path

import pytest

from aso.execution.catalog import ExecutorCatalog, ExecutorProfile, managed_codex_profiles
from aso.execution.cli_provider import CliAgentExecutionProvider
from aso.execution.codex_discovery import CodexCapabilities, CodexModel


def _capabilities() -> CodexCapabilities:
    return CodexCapabilities(
        binary="/usr/bin/codex",
        version="codex-cli 1.2.3",
        models=(CodexModel("gpt-x", "GPT X", True, "medium", ("low", "medium", "high")),),
    )


def test_managed_profiles_tem_default_sem_modelo() -> None:
    profiles = managed_codex_profiles(_capabilities(), wrapper="/tmp/wrapper")
    assert [profile.name for profile in profiles] == ["codex-default", "codex-gpt-x"]
    assert profiles[0].model == ""
    assert "-m" not in profiles[0].command
    assert "--ignore-user-config" in profiles[0].command
    assert profiles[1].supported_efforts == ["low", "medium", "high"]


def test_replace_managed_preserva_customizado_e_remove_legados() -> None:
    catalog = ExecutorCatalog(
        [
            ExecutorProfile(name="custom", kind="cli", command="custom"),
            ExecutorProfile(name="codex-gpt-5-medium", kind="cli", command="velho"),
        ]
    )
    catalog.replace_managed_codex(managed_codex_profiles(_capabilities(), wrapper="/tmp/w"))
    names = {profile.name for profile in catalog.profiles()}
    assert "custom" in names
    assert "codex-gpt-5-medium" not in names
    assert {"codex-default", "codex-gpt-x"} <= names


def test_seed_legado_fica_indisponivel_antes_da_sincronizacao() -> None:
    catalog = ExecutorCatalog(
        [ExecutorProfile(name="codex-gpt-5-medium", kind="cli", command="codex -m gpt-5")]
    )
    public = next(item for item in catalog.entries() if item["name"] == "codex-gpt-5-medium")
    assert public["available"] is False
    with pytest.raises(ValueError, match="perfil legado"):
        catalog.validate("codex-gpt-5-medium")


def test_build_aplica_modelo_e_esforco_validados(tmp_path: Path) -> None:
    profile = managed_codex_profiles(_capabilities(), wrapper="/tmp/w")[1]
    catalog = ExecutorCatalog([profile])
    provider = catalog.build("codex-gpt-x", repo_override=str(tmp_path), effort_override="high")
    assert isinstance(provider, CliAgentExecutionProvider)
    assert provider.command[-4:] == ["-m", "gpt-x", "-c", "model_reasoning_effort=high"]
    with pytest.raises(ValueError, match="não é aceito"):
        catalog.build("codex-gpt-x", repo_override=str(tmp_path), effort_override="ultra")
