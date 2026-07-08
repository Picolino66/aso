"""(c) Endpoint de corrida de candidatos CLI + comparação no console (§26A.6).

Cobre o `POST .../cards/{cid}/race`: constrói os agentes candidatos a partir do
ambiente (ASO_CANDIDATE_COMMANDS + ASO_TARGET_REPO), roda em paralelo em worktrees
isolados e devolve a comparação de diffs; e o 409 quando nada está configurado.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "README.md").write_text("base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "init")


def test_race_endpoint_compares_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    monkeypatch.setenv("ASO_TARGET_REPO", str(repo))
    monkeypatch.setenv(
        "ASO_CANDIDATE_COMMANDS",
        json.dumps(
            [
                {"id": "claude", "command": 'bash -c "echo a > sol_claude.py"'},
                {"id": "codex", "command": "bash -c \"printf 'a\\nb\\nc\\n' > sol_codex.py\""},
            ]
        ),
    )
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("implementar no backend")
    card = svc.get_cards(orch.id)[0]

    resp = client.post(f"/v1/orchestrations/{orch.id}/cards/{card.id}/race")
    assert resp.status_code == 200
    comparison = resp.json()
    assert {c["executor"] for c in comparison["candidates"]} == {"claude", "codex"}
    assert comparison["recommended_branch"] in {c["branch"] for c in comparison["candidates"]}
    # candidatos tocam arquivos diferentes, em worktrees isolados
    files = {tuple(c["files"]) for c in comparison["candidates"]}
    assert files == {("sol_claude.py",), ("sol_codex.py",)}
    # o diff de cada candidato acompanha a comparação (para o painel lado a lado)
    claude = next(c for c in comparison["candidates"] if c["executor"] == "claude")
    assert "sol_claude.py" in claude["diff"]


def test_race_endpoint_409_when_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ASO_CANDIDATE_COMMANDS", raising=False)
    monkeypatch.delenv("ASO_TARGET_REPO", raising=False)
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]

    resp = client.post(f"/v1/orchestrations/{orch.id}/cards/{card.id}/race")
    assert resp.status_code == 409
    assert "candidato" in resp.json()["detail"].lower()
