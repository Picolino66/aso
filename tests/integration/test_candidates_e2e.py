"""(b) Ponta a ponta via API: corrida de candidatos → PR do recomendado → merge governado.

Exercita o fluxo completo com git real (worktrees isolados), como um agente CLI real
faria — trocar `ASO_CANDIDATE_COMMANDS` por `claude`/`codex` é só configuração. Aqui os
"agentes CLI" são comandos determinísticos que editam arquivos, para o teste ser
reproduzível sem depender de um binário de LLM instalado.
"""

from __future__ import annotations

import json
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


def test_candidates_to_governed_merge_via_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    monkeypatch.setenv("ASO_TARGET_REPO", str(repo))
    monkeypatch.setenv(
        "ASO_CANDIDATE_COMMANDS",
        json.dumps(
            [
                {"id": "claude", "command": 'bash -c "echo pequeno > sol.py"'},
                {"id": "codex", "command": "bash -c \"printf 'a\\nb\\nc\\nd\\n' > grande.py\""},
            ]
        ),
    )
    # provider de merge (WorktreeManager no mesmo repo alvo) — o que build_service faria em prod.
    svc = OrchestrationService(
        provider=CliAgentExecutionProvider(["bash", "-c", "true"], str(repo))
    )
    client = TestClient(create_app(svc))

    orch = client.post("/v1/orchestrations", json={"user_request": "implementar no backend"}).json()
    oid = orch["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]

    # 1) corrida de candidatos: menor diff válido = branch do "claude" (1 linha)
    comparison = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/race").json()
    recommended = comparison["recommended_branch"]
    winner = next(c for c in comparison["candidates"] if c["branch"] == recommended)
    assert winner["executor"] == "claude"
    assert winner["files"] == ["sol.py"]

    # 2) abre PR do recomendado → card em Review
    pr = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/open-pr", json={"branch": recommended}
    ).json()
    assert client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["status"] == "Review"

    # 3) merge bloqueado sem CI + review (governança §26A.6)
    blocked = client.post(f"/v1/orchestrations/{oid}/pulls/{pr['id']}/merge")
    assert blocked.status_code == 409

    # 4) CI passed + review approved → merge governado (git real na base)
    client.post(f"/v1/orchestrations/{oid}/pulls/{pr['id']}/ci", json={"status": "passed"})
    client.post(f"/v1/orchestrations/{oid}/pulls/{pr['id']}/review", json={"status": "approved"})
    merged = client.post(f"/v1/orchestrations/{oid}/pulls/{pr['id']}/merge")
    assert merged.status_code == 200
    assert merged.json()["status"] == "merged"

    # 5) o candidato recomendado foi mesclado na base; o perdedor não
    assert (repo / "sol.py").exists()
    assert not (repo / "grande.py").exists()
    assert client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["status"] == "Done"
