"""Teste de estresse da corrida de candidatos (plano6 §0/§6).

Reproduz, com repetição, a falha intermitente observada na suíte completa
(`test_race_candidates_and_merge_recommended` falhando ~2 de 5 execuções): um
candidato concorrente volta com `error` mesmo com comando determinístico. Uma
corrida isolada não prova nada — a contenção só aparece sob repetição.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from aso.control.orchestration_service import OrchestrationService
from aso.execution.cli_provider import CliAgentExecutionProvider

_N = int(os.environ.get("ASO_RACE_STRESS_N", "20"))


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "README.md").write_text("base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "init")


def test_race_nunca_perde_candidato_sob_repeticao(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    providers = [
        CliAgentExecutionProvider(["bash", "-c", "echo a > sol_a.py"], str(repo), executor_id="a"),
        CliAgentExecutionProvider(
            ["bash", "-c", "printf 'a\\nb\\nc\\n' > sol_b.py"], str(repo), executor_id="b"
        ),
        CliAgentExecutionProvider(["bash", "-c", "echo c > sol_c.py"], str(repo), executor_id="c"),
    ]
    svc = OrchestrationService()
    orch = svc.create_orchestration("implementar no backend")
    card = svc.get_cards(orch.id)[0]

    falhas: list[dict[str, object]] = []
    for i in range(_N):
        comparison = svc.race_card(orch.id, card.id, providers)
        assert comparison["falhas"] == [
            {"executor": c["executor"], "erro": c["error"]}
            for c in comparison["candidates"]
            if c["error"]
        ]
        for c in comparison["candidates"]:
            if c["error"]:
                falhas.append({"rodada": i, **c})

    assert not falhas, f"{len(falhas)}/{_N * len(providers)} candidatos falharam: {falhas[:5]}"
