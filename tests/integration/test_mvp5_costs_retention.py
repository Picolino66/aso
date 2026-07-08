"""(b) Timeline de custo por card (F7 avançado) + (d) retenção de corridas (§26A.6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from aso.agents.executor import LocalMockExecutionProvider
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


def test_execution_timeline_groups_cost_by_card() -> None:
    svc = OrchestrationService(provider=LocalMockExecutionProvider())
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)

    client = TestClient(create_app(svc))
    t = client.get(f"/v1/orchestrations/{orch.id}/execution-timeline").json()

    assert t["executions_total"] >= 1
    entry = next(c for c in t["cards"] if c["card_id"] == card.id)
    assert entry["executions"] >= 1
    assert entry["total_ms"] >= 0.0
    assert entry["avg_ms"] >= 0.0
    assert entry["runs"]  # detalhe por execução (agente, ms, ok, at)


def test_race_retention_prunes_oldest(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    svc = OrchestrationService(max_races_per_card=2)
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]

    for i in range(3):
        provider = CliAgentExecutionProvider(["bash", "-c", f"echo {i} > f.py"], str(repo))
        svc.race_card(orch.id, card.id, [provider])

    runs = svc.list_candidate_runs(orch.id, card.id)
    assert len(runs) == 2  # retenção manteve apenas as 2 corridas mais recentes
    # sobrevive à reidratação com o mesmo limite aplicado na escrita
    svc._bundles.clear()  # noqa: SLF001
    assert len(svc.list_candidate_runs(orch.id, card.id)) == 2
