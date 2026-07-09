"""(a)/(b) Fluxo de PR (CI/review) + merge governado real (§26, MVP-4)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.execution.cli_provider import CliAgentExecutionProvider


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "README.md").write_text("base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "init")


def test_governed_merge_real_git(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    provider = CliAgentExecutionProvider(["bash", "-c", "echo 'gerado' > feature.py"], str(repo))
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration("implementar no backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)  # cria branch com commit

    pr = svc.open_pr(orch.id, card.id)
    assert pr.status == "open"
    assert svc.get_cards(orch.id)[0].status.value == "Review"

    # merge sem CI/review aprovados => bloqueado (governança §26A.6)
    with pytest.raises(ValueError):
        svc.merge_pr(orch.id, pr.id)

    svc.report_ci(orch.id, pr.id, "passed")
    svc.report_review(orch.id, pr.id, "approved")
    merged = svc.merge_pr(orch.id, pr.id)

    assert merged.status == "merged"
    assert svc.get_cards(orch.id)[0].status.value == "Done"
    # o merge git real trouxe o arquivo para a branch base
    assert (repo / "feature.py").exists()


def test_ci_failure_moves_card_to_failed(tmp_path: Path) -> None:
    repo = tmp_path / "ci-failure"
    _init_repo(repo)
    svc = OrchestrationService(
        provider=CliAgentExecutionProvider(["bash", "-c", "echo x > f.txt"], str(repo))
    )
    orch = svc.create_orchestration("x")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)
    pr = svc.list_pulls(orch.id)[0]
    svc.report_ci(orch.id, pr.id, "failed")
    assert svc.get_cards(orch.id)[0].status.value == "Failed"


def test_pr_endpoints_and_merge_governance() -> None:
    client = TestClient(create_app(OrchestrationService()))  # mock provider (merge lógico)
    oid = client.post("/v1/orchestrations", json={"user_request": "x"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    response = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/open-pr", json={"title": "PR X"}
    )
    assert response.status_code == 201  # compatibilidade com o provider mock legado
