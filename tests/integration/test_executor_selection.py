"""(M6 + seleção) Catálogo de executores por etapa, esforço e kill-switch."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aso.agents.executor import LocalMockExecutionProvider
from aso.agents.models import AgentSpec
from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile, build_catalog_from_env


def _svc() -> OrchestrationService:
    catalog = ExecutorCatalog([ExecutorProfile(name="mock", kind="mock", is_default=True)])
    return OrchestrationService(catalog=catalog)


def test_catalog_from_env_parses_profiles_and_marks_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ASO_EXECUTORS",
        json.dumps(
            [
                {"name": "claude", "kind": "cli", "command": "claude -p", "model": "sonnet"},
                {"name": "deepseek", "kind": "llm", "provider": "deepseek", "model": "ds-chat"},
            ]
        ),
    )
    cat = build_catalog_from_env()
    names = {p["name"] for p in cat.entries()}
    assert {"claude", "deepseek", "mock"} <= names
    # perfis públicos não expõem segredos/command
    claude = next(p for p in cat.entries() if p["name"] == "claude")
    assert claude["model"] == "sonnet"
    assert "low" in claude["efforts"]
    assert cat.default_name() == "claude"  # 1º vira default


def test_catalog_build_mock_and_unknown() -> None:
    cat = ExecutorCatalog()
    assert isinstance(cat.build("mock"), LocalMockExecutionProvider)
    with pytest.raises(KeyError):
        cat.build("inexistente")


def test_build_task_threads_effort() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend")
    b = svc._bundle(orch.id)  # noqa: SLF001
    card = svc.get_cards(orch.id)[0]
    agent = AgentSpec(role="X")
    task = svc._build_task(b, card, agent, effort="high")  # noqa: SLF001
    assert task["effort"] == "high"


def test_run_phase_with_executor_records_choice_in_approval() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend")
    result = svc.run_phase(orch.id, executor="mock", effort="high")
    assert result["gate_status"] == "PASSED"
    ap = next(a for a in svc.list_approvals(orch.id) if a.id == result["approval_id"])
    assert ap.payload["executor"] == "mock"
    assert ap.payload["effort"] == "high"


def test_kill_switch_blocks_run_when_cancelled() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend")
    svc.cancel(orch.id)
    with pytest.raises(ValueError, match="cancelada"):
        svc.run_phase(orch.id)


def test_executors_endpoint_and_run_phase_body() -> None:
    client = TestClient(create_app(_svc()))
    execs = client.get("/v1/executors").json()
    assert any(e["name"] == "mock" for e in execs)

    oid = client.post("/v1/orchestrations", json={"user_request": "X"}).json()["id"]
    res = client.post(
        f"/v1/orchestrations/{oid}/run-phase", json={"executor": "mock", "effort": "low"}
    )
    assert res.status_code == 200
    assert res.json()["gate_status"] == "PASSED"
