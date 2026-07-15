"""(Config) Tela de configurações de executores: CRUD + persistência (sem secrets)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.codex_discovery import CodexCapabilities, CodexModel
from aso.execution.settings_store import ExecutorSettingsStore


def _svc(tmp_path: Path) -> OrchestrationService:
    store = ExecutorSettingsStore(str(tmp_path / "executors.json"))
    catalog = ExecutorCatalog(store.load())
    return OrchestrationService(catalog=catalog, executor_store=store)


def test_save_and_delete_executor_persists(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    svc.save_executor(
        ExecutorProfile(name="claude", kind="cli", command="claude -p", model="sonnet")
    )
    names = {e["name"] for e in svc.list_executors()}
    assert {"claude", "mock"} <= names

    # persiste em disco (sem o executor 'mock')
    reloaded = ExecutorSettingsStore(str(tmp_path / "executors.json")).load()
    assert [p.name for p in reloaded] == ["claude"]

    svc.delete_executor("claude")
    assert "claude" not in {e["name"] for e in svc.list_executors()}


def test_mock_cannot_be_removed(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(ValueError, match="mock"):
        svc.delete_executor("mock")


def test_llm_key_status_reflects_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(tmp_path)
    svc.save_executor(
        ExecutorProfile(
            name="deepseek", kind="llm", provider="deepseek", model="ds", api_key_env="ASO_DS_KEY"
        )
    )
    ds = next(e for e in svc.list_executors() if e["name"] == "deepseek")
    assert ds["has_key"] is False  # env var ausente
    monkeypatch.setenv("ASO_DS_KEY", "segredo")
    ds = next(e for e in svc.list_executors() if e["name"] == "deepseek")
    assert ds["has_key"] is True
    # a listagem nunca expõe o valor da chave
    assert "segredo" not in str(svc.list_executors())


def test_executor_crud_endpoints(tmp_path: Path) -> None:
    client = TestClient(create_app(_svc(tmp_path)))
    created = client.post(
        "/v1/executors",
        json={"name": "codex", "kind": "cli", "command": "codex exec"},
    )
    assert created.status_code == 201
    assert any(e["name"] == "codex" for e in created.json())

    listed = client.get("/v1/executors").json()
    assert any(e["name"] == "codex" for e in listed)

    removed = client.delete("/v1/executors/codex")
    assert removed.status_code == 200
    assert not any(e["name"] == "codex" for e in removed.json())

    # 'mock' protegido → 409
    assert client.delete("/v1/executors/mock").status_code == 409


def test_sync_codex_idempotente_preserva_customizado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = _svc(tmp_path)
    svc.save_executor(ExecutorProfile(name="custom", kind="cli", command="custom"))
    svc.save_executor(ExecutorProfile(name="codex-gpt-5-medium", kind="cli", command="legado"))
    capabilities = CodexCapabilities(
        binary="/usr/bin/codex",
        version="codex-cli 1",
        models=(CodexModel("gpt-atual", "GPT atual", True, "medium", ("low", "medium")),),
    )
    monkeypatch.setattr("aso.control.orchestration_service.discover_codex", lambda: capabilities)
    first = svc.sync_codex_executors()
    second = svc.sync_codex_executors()
    assert first == second
    names = {item["name"] for item in second}
    assert {"custom", "codex-default", "codex-gpt-atual"} <= names
    assert "codex-gpt-5-medium" not in names
    reloaded = ExecutorSettingsStore(str(tmp_path / "executors.json")).load()
    assert {profile.name for profile in reloaded} == {
        "custom",
        "codex-default",
        "codex-gpt-atual",
    }


def test_sync_codex_concorrente_nao_duplica(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = _svc(tmp_path)
    capabilities = CodexCapabilities(
        binary="/usr/bin/codex",
        version="codex-cli 1",
        models=(CodexModel("gpt-atual", "GPT atual", True, "medium", ("medium",)),),
    )
    monkeypatch.setattr("aso.control.orchestration_service.discover_codex", lambda: capabilities)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: svc.sync_codex_executors(), range(8)))
    assert all(result == results[0] for result in results)
    assert [profile.name for profile in svc._catalog.profiles()].count(  # type: ignore[union-attr]  # noqa: SLF001
        "codex-default"
    ) == 1
